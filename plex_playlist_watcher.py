"""Watch configured folders, add indexed videos to paired Plex playlists,
and sort each playlist by duration.

The watcher deliberately waits for a file to stop changing before asking Plex
to scan. Plex scans are asynchronous, so it then polls the library until the
new item's file path appears.
"""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import logging
import ntpath
import os
import queue
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dataclasses import dataclass
from threading import Event, Thread
from typing import Iterable

import discord
from plexapi.exceptions import PlexApiException
from plexapi.server import PlexServer
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


LOG = logging.getLogger("plex-playlist-watcher")
DEFAULT_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}

# A sleeping Windows system pauses the asyncio event loop and Discord
# heartbeats.  Once the loop resumes, proactively close the old gateway socket
# so discord.py's normal reconnect loop establishes a live connection again.
# The threshold is deliberately longer than a normal scheduling hiccup while
# still recovering promptly from a suspend/resume cycle.
DISCORD_SLEEP_CHECK_SECONDS = 15
DISCORD_SLEEP_GAP_SECONDS = 60


def normalized_path(value: str) -> str:
    """Normalize Windows paths for comparison with paths returned by Plex."""

    return ntpath.normcase(ntpath.normpath(value.replace("/", "\\")))


def item_files(item) -> Iterable[str]:
    """Yield media-part file paths represented by a Plex item."""

    for media in getattr(item, "media", []) or []:
        for part in getattr(media, "parts", []) or []:
            filename = getattr(part, "file", None)
            if filename:
                yield filename


def item_identity(item) -> str:
    """Return the playlist-specific identity when available."""

    playlist_item_id = getattr(item, "playlistItemID", None)
    if playlist_item_id is not None:
        return f"playlist:{playlist_item_id}"
    return f"rating:{getattr(item, 'ratingKey', '')}"


def duration_sort_key(item):
    duration = getattr(item, "duration", None)
    # Items whose duration is not available yet go to the end.
    return (
        duration is None,
        duration if duration is not None else 0,
        (getattr(item, "title", "") or "").casefold(),
        str(getattr(item, "ratingKey", "")),
    )


@dataclass(frozen=True)
class WatchJob:
    name: str
    watch_folder: Path
    plex_library_folder: str
    plex_scan_path: str
    library: str
    playlist: str
    extensions: frozenset[str]
    settle_seconds: float
    file_timeout: float
    plex_timeout: float
    poll_interval: float
    batch_seconds: float
    folder_poll_seconds: float
    scan: bool


class PlexPlaylistWatcher:
    def __init__(self, plex: PlexServer, job: WatchJob, on_items_added=None):
        self.plex = plex
        self.job = job
        self.on_items_added = on_items_added
        self.stop_event = Event()
        self.pending: queue.Queue[str] = queue.Queue()
        self.known_files: set[str] = set()
        self.section = self.plex.library.section(job.library)
        self.playlist = self.plex.playlist(job.playlist)

        if getattr(self.playlist, "smart", False):
            raise ValueError(
                f"Playlist {job.playlist!r} is a smart playlist. "
                "Use a regular playlist because smart playlists cannot be reordered."
            )

        if not job.watch_folder.is_dir():
            raise ValueError(f"Watched folder does not exist or is not a directory: {job.watch_folder}")
        self.watch_folder = job.watch_folder
        self.plex_folder = job.plex_library_folder

    def enqueue(self, path: str) -> None:
        if self.stop_event.is_set():
            return
        candidate = Path(path)
        if candidate.suffix.casefold() not in self.job.extensions:
            return
        LOG.debug("[%s] Queued file event: %s", self.job.name, candidate)
        self.pending.put(str(candidate))

    def supported_files(self) -> set[str]:
        files = set()
        try:
            for path in self.watch_folder.rglob("*"):
                if path.is_file() and path.suffix.casefold() in self.job.extensions:
                    files.add(str(path))
        except OSError as exc:
            LOG.warning("[%s] Could not enumerate watched folder: %s", self.job.name, exc)
        return files

    def discover_new_files(self) -> None:
        """Catch file arrivals missed while Windows or the watcher was asleep."""

        current_files = self.supported_files()
        new_files = current_files - self.known_files
        self.known_files = current_files
        for path in sorted(new_files):
            LOG.info("[%s] Discovery found new file: %s", self.job.name, path)
            self.enqueue(path)

    def plex_path_for(self, local_path: Path) -> str:
        """Map a local watched path to the path visible to Plex."""

        try:
            relative = local_path.resolve().relative_to(self.watch_folder)
        except ValueError:
            relative = Path(local_path.name)
        return ntpath.join(self.plex_folder, *relative.parts)

    def wait_until_stable(self, path: Path) -> bool:
        """Wait until the file exists and its size/mtime stop changing."""

        deadline = time.monotonic() + self.job.file_timeout
        previous = None
        stable_since = None

        while not self.stop_event.is_set() and time.monotonic() < deadline:
            try:
                stat = path.stat()
            except FileNotFoundError:
                time.sleep(self.job.poll_interval)
                continue

            signature = (stat.st_size, stat.st_mtime_ns)
            now = time.monotonic()
            if signature != previous:
                previous = signature
                stable_since = now
            elif stable_since is not None and now - stable_since >= self.job.settle_seconds:
                return True

            time.sleep(self.job.poll_interval)

        LOG.warning("File did not become stable before timeout: %s", path)
        return False

    def collect_batch(self, first: str) -> set[str]:
        """Collect events briefly so one copy operation causes one scan."""

        batch = {first}
        deadline = time.monotonic() + self.job.batch_seconds
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                batch.add(self.pending.get(timeout=remaining))
            except queue.Empty:
                break
        return batch

    def find_item_by_path(self, plex_path: str):
        target = normalized_path(plex_path)
        for item in self.section.all():
            if any(normalized_path(filename) == target for filename in item_files(item)):
                return item
        return None

    def wait_for_item(self, plex_path: str):
        deadline = time.monotonic() + self.job.plex_timeout
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            item = self.find_item_by_path(plex_path)
            if item is not None:
                # A just-indexed item may not have duration populated yet.
                if getattr(item, "duration", None) is not None:
                    return item
                try:
                    item.reload()
                except PlexApiException:
                    pass
                if getattr(item, "duration", None) is not None:
                    return item
            time.sleep(self.job.poll_interval)
        return None

    def add_missing_items(self, items: list) -> list:
        playlist = self.plex.playlist(self.job.playlist)
        existing_rating_keys = {
            getattr(item, "ratingKey", None) for item in playlist.items()
        }
        missing = [
            item
            for item in items
            if getattr(item, "ratingKey", None) not in existing_rating_keys
        ]

        if missing:
            playlist.addItems(missing)
            LOG.info("[%s] Added %d item(s) to playlist %r", self.job.name, len(missing), self.job.playlist)
        return missing

    def sort_playlist(self) -> None:
        """Sort using Plex's move endpoint, refreshing after every move."""

        playlist = self.plex.playlist(self.job.playlist)
        desired = sorted(playlist.items(), key=duration_sort_key)
        desired_ids = [item_identity(item) for item in desired]

        for desired_index, desired_id in enumerate(desired_ids):
            current = playlist.items()
            current_by_id = {item_identity(item): item for item in current}
            target = current_by_id[desired_id]

            # Remove the target conceptually before finding the item that will
            # precede it. This avoids trying to move an item after itself.
            without_target = [
                item for item in current if item_identity(item) != desired_id
            ]
            if desired_index == 0:
                after = None
            else:
                after = without_target[desired_index - 1]

            if desired_index < len(current) and item_identity(current[desired_index]) == desired_id:
                continue

            playlist.moveItem(target, after=after)

        LOG.info("[%s] Sorted playlist %r by shortest video duration first", self.job.name, self.job.playlist)

    def process_batch(self, paths: set[str]) -> None:
        candidates = [
            Path(raw_path)
            for raw_path in sorted(paths)
            if Path(raw_path).suffix.casefold() in self.job.extensions
        ]
        LOG.info("[%s] Processing batch of %d file event(s)", self.job.name, len(candidates))

        # Stability checks are independent filesystem operations. Running them
        # concurrently prevents startup reconciliation from delaying a newly
        # arrived file by several seconds per existing file.
        with ThreadPoolExecutor(max_workers=min(16, max(1, len(candidates)))) as executor:
            stable_results = executor.map(self.wait_until_stable, candidates)
            stable_paths = [
                path for path, is_stable in zip(candidates, stable_results) if is_stable
            ]

        if not stable_paths:
            return

        if self.job.scan:
            scan_path = self.job.plex_scan_path
            LOG.info("[%s] Requesting Plex scan of %s", self.job.name, scan_path)
            self.section.update(path=scan_path)

        indexed_items = []
        for local_path in stable_paths:
            plex_path = self.plex_path_for(local_path)
            item = self.wait_for_item(plex_path)
            if item is None:
                LOG.warning(
                    "Plex did not expose %s within %.0f seconds; check path mapping",
                    plex_path,
                    self.job.plex_timeout,
                )
                continue
            indexed_items.append(item)
            LOG.info("Found %r (%s ms)", item.title, item.duration)

        if indexed_items:
            added_items = self.add_missing_items(indexed_items)
            self.sort_playlist()
            if added_items and self.on_items_added:
                self.on_items_added(self.job, added_items)

    def worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                first = self.pending.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.process_batch(self.collect_batch(first))
            except Exception:
                LOG.exception("Batch processing failed")

    def run(self) -> None:
        worker = Thread(target=self.worker, name="plex-worker", daemon=True)
        worker.start()

        handler = WatchHandler(self)
        observer = Observer()
        observer.schedule(handler, str(self.watch_folder), recursive=True)
        observer.start()
        LOG.info("[%s] Watching %s", self.job.name, self.watch_folder)
        self.known_files = self.supported_files()
        LOG.info(
            "[%s] Ignoring %d file(s) already present at startup",
            self.job.name,
            len(self.known_files),
        )

        try:
            next_discovery = time.monotonic() + self.job.folder_poll_seconds
            while not self.stop_event.wait(1):
                if time.monotonic() >= next_discovery:
                    self.discover_new_files()
                    next_discovery = time.monotonic() + self.job.folder_poll_seconds
        finally:
            observer.stop()
            observer.join()
            self.stop_event.set()
            worker.join(timeout=2)

    def stop(self, *_args) -> None:
        self.stop_event.set()


class WatchHandler(FileSystemEventHandler):
    def __init__(self, watcher: PlexPlaylistWatcher):
        self.watcher = watcher

    def on_created(self, event):
        if not event.is_directory:
            self.watcher.enqueue(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.watcher.enqueue(event.dest_path)


def load_settings(filename: str) -> dict:
    path = Path(filename)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(settings, dict):
        raise SystemExit(f"Settings file must contain a JSON object: {path}")
    return settings


def format_duration(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "unknown length"
    total_seconds = max(0, int(milliseconds / 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class PlexDiscordBot(discord.Client):
    """Discord client that owns the local filesystem/Plex watcher."""

    def __init__(self, args: argparse.Namespace):
        # No message, member, or presence intent is needed: this bot only
        # sends DMs and does not process Discord commands.
        super().__init__(intents=discord.Intents.none())
        self.args = args
        self.watchers = [
            PlexPlaylistWatcher(
                PlexServer(args.plex_url, args.plex_token),
                job,
                on_items_added=self.items_added,
            )
            for job in args.jobs
        ]
        self.watcher_thread_tasks = []
        self.notification_loop = None
        self.sleep_monitor_task = None

    async def setup_hook(self):
        """Start the sleep detector before the gateway connection begins."""

        self.sleep_monitor_task = asyncio.create_task(self.monitor_system_sleep())

    async def monitor_system_sleep(self) -> None:
        """Reconnect Discord after the event loop was suspended for a while."""

        last_monotonic = time.monotonic()
        last_wall_clock = time.time()
        reconnect_pending = False

        while not self.is_closed():
            await asyncio.sleep(DISCORD_SLEEP_CHECK_SECONDS)

            current_monotonic = time.monotonic()
            current_wall_clock = time.time()
            monotonic_gap = current_monotonic - last_monotonic
            wall_clock_gap = current_wall_clock - last_wall_clock
            last_monotonic = current_monotonic
            last_wall_clock = current_wall_clock

            # Use both clocks: on some Windows configurations the monotonic
            # clock pauses during sleep, while wall-clock time still advances.
            if max(monotonic_gap, wall_clock_gap) >= DISCORD_SLEEP_GAP_SECONDS:
                reconnect_pending = True
                LOG.warning(
                    "Detected a %.0f-second system/event-loop gap; "
                    "refreshing the Discord gateway connection",
                    max(monotonic_gap, wall_clock_gap),
                )

            if reconnect_pending and self.ws is not None:
                try:
                    # Code 1000 tells discord.py to stay in its reconnect
                    # loop. This keeps watcher threads and their startup
                    # baseline alive while replacing the stale socket.
                    await asyncio.wait_for(self.ws.close(code=1000), timeout=10)
                    reconnect_pending = False
                except asyncio.TimeoutError:
                    LOG.exception("Timed out closing the stale Discord gateway socket")
                except Exception:
                    LOG.exception("Could not refresh the Discord gateway connection")

    async def on_disconnect(self):
        LOG.warning("Discord gateway disconnected; waiting for reconnect")

    async def on_resumed(self):
        LOG.info("Discord gateway session resumed")

    async def on_ready(self):
        self.notification_loop = asyncio.get_running_loop()
        LOG.info("Discord bot logged in as %s", self.user)
        if not self.watcher_thread_tasks:
            self.watcher_thread_tasks = [
                asyncio.create_task(asyncio.to_thread(watcher.run))
                for watcher in self.watchers
            ]

    def items_added(self, job: WatchJob, items: list) -> None:
        """Called by the Plex worker thread after a playlist update."""

        if self.notification_loop is None:
            LOG.warning("Skipping Discord notification because bot is not ready")
            return
        future = asyncio.run_coroutine_threadsafe(
            self.send_added_notification(job, items), self.notification_loop
        )
        future.add_done_callback(self.notification_done)

    @staticmethod
    def notification_done(future) -> None:
        try:
            future.result()
        except Exception:
            LOG.exception("Could not send Discord notification")

    async def send_added_notification(self, job: WatchJob, items: list) -> None:
        user = await self.fetch_user(self.args.discord_user_id)
        lines = [
            f"Added {len(items)} video(s) to Plex playlist "
            f"**{job.playlist}** ({job.name}) and sorted shortest-first:",
        ]
        for item in items:
            lines.append(
                f"• {item.title} — {format_duration(getattr(item, 'duration', None))}"
            )
        message = "\n".join(lines)

        # Discord limits a message to 2,000 characters. A large copy batch is
        # split into multiple DMs while preserving the useful summary header.
        chunks = []
        current = ""
        for line in message.splitlines():
            if current and len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = ""
            current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)
        for chunk in chunks:
            await user.send(chunk)

    async def close(self):
        for watcher in self.watchers:
            watcher.stop()
        await super().close()


def run_discord_bot(args: argparse.Namespace) -> None:
    bot = PlexDiscordBot(args)
    bot.run(args.discord_token, log_handler=None)


def configure_logging(args: argparse.Namespace) -> Path:
    log_path = Path(args.log_file).expanduser()
    if not log_path.is_absolute():
        log_path = Path(__file__).resolve().parent / log_path
    date_stamp = datetime.now().strftime("%Y-%m-%d")
    log_path = log_path.with_name(f"{log_path.stem}-{date_stamp}{log_path.suffix}")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=args.log_max_bytes,
        backupCount=args.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        handlers=[file_handler, console_handler],
        force=True,
    )
    logging.getLogger(__name__).info(
        "Logging to %s (max %d bytes, %d backups)",
        log_path,
        args.log_max_bytes,
        args.log_backup_count,
    )
    return log_path


def normalized_extensions(values) -> frozenset[str]:
    extensions = set()
    for value in values:
        extension = str(value).casefold()
        extensions.add(extension if extension.startswith(".") else f".{extension}")
    return frozenset(extensions)


def build_jobs(settings: dict) -> list[WatchJob]:
    """Build independent watcher jobs from the settings JSON."""

    raw_jobs = settings.get("jobs")
    if raw_jobs is None:
        # Accept the old single-job format during migration.
        if settings.get("watch_folder"):
            raw_jobs = [settings]
        else:
            raise ValueError("settings.json must contain a non-empty 'jobs' list")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ValueError("settings.json 'jobs' must be a non-empty list")

    defaults = {
        "extensions": settings.get("extensions", sorted(DEFAULT_EXTENSIONS)),
        "settle_seconds": settings.get("settle_seconds", 5),
        "file_timeout": settings.get("file_timeout", 3600),
        "plex_timeout": settings.get("plex_timeout", 300),
        "poll_interval": settings.get("poll_interval", 3),
        "batch_seconds": settings.get("batch_seconds", 8),
        "folder_poll_seconds": settings.get("folder_poll_seconds", 30),
        "scan": settings.get("scan", True),
    }
    jobs = []
    for index, raw_job in enumerate(raw_jobs, start=1):
        if not isinstance(raw_job, dict):
            raise ValueError(f"jobs[{index - 1}] must be a JSON object")
        watch_folder_value = raw_job.get("watch_folder")
        library = raw_job.get("library")
        playlist = raw_job.get("playlist")
        if not watch_folder_value or not library or not playlist:
            raise ValueError(
                f"jobs[{index - 1}] requires watch_folder, library, and playlist"
            )

        watch_folder = Path(watch_folder_value).expanduser().resolve()
        plex_library_folder = raw_job.get("plex_library_folder") or str(watch_folder)
        plex_scan_path = raw_job.get("plex_scan_path") or plex_library_folder
        name = raw_job.get("name") or f"{library} → {playlist}"
        jobs.append(
            WatchJob(
                name=str(name),
                watch_folder=watch_folder,
                plex_library_folder=str(plex_library_folder),
                plex_scan_path=str(plex_scan_path),
                library=str(library),
                playlist=str(playlist),
                extensions=normalized_extensions(
                    raw_job.get("extensions", defaults["extensions"])
                ),
                settle_seconds=float(raw_job.get("settle_seconds", defaults["settle_seconds"])),
                file_timeout=float(raw_job.get("file_timeout", defaults["file_timeout"])),
                plex_timeout=float(raw_job.get("plex_timeout", defaults["plex_timeout"])),
                poll_interval=float(raw_job.get("poll_interval", defaults["poll_interval"])),
                batch_seconds=float(raw_job.get("batch_seconds", defaults["batch_seconds"])),
                folder_poll_seconds=float(
                    raw_job.get("folder_poll_seconds", defaults["folder_poll_seconds"])
                ),
                scan=bool(raw_job.get("scan", defaults["scan"])),
            )
        )
    return jobs


def parse_args() -> argparse.Namespace:
    # Parse this option first so settings can provide argparse defaults while
    # command-line arguments continue to take precedence.
    settings_parser = argparse.ArgumentParser(add_help=False)
    settings_parser.add_argument("--settings", default="settings.json")
    settings_args, _ = settings_parser.parse_known_args()
    settings = load_settings(settings_args.settings)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settings",
        default=settings_args.settings,
        help="JSON settings file (default: settings.json)",
    )
    parser.add_argument(
        "--plex-url",
        default=os.environ.get(
            "PLEX_URL", settings.get("plex_url", "http://127.0.0.1:32400")
        ),
        help="Plex server URL (or set PLEX_URL)",
    )
    parser.add_argument(
        "--plex-token",
        default=os.environ.get("PLEX_TOKEN", settings.get("plex_token")),
        help="Plex token (or set PLEX_TOKEN)",
    )
    parser.add_argument(
        "--discord-token",
        default=os.environ.get("DISCORD_TOKEN", settings.get("discord_token")),
        help="Discord bot token (or set DISCORD_TOKEN)",
    )
    parser.add_argument(
        "--discord-user-id",
        type=int,
        default=settings.get("discord_user_id"),
        help="Discord user ID that should receive DMs",
    )
    parser.add_argument(
        "--log-file",
        default=settings.get("log_file", "logs/plex_playlist_watcher.log"),
        help="Log file path, relative to this project by default",
    )
    parser.add_argument(
        "--log-max-bytes",
        type=int,
        default=settings.get("log_max_bytes", 5 * 1024 * 1024),
        help="Rotate the log after this many bytes",
    )
    parser.add_argument(
        "--log-backup-count",
        type=int,
        default=settings.get("log_backup_count", 5),
        help="Number of rotated log files to retain",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.plex_token or args.plex_token == "PUT_YOUR_PLEX_TOKEN_HERE":
        parser.error("Provide --plex-token, set PLEX_TOKEN, or fill in settings.json")
    if not args.discord_token or args.discord_token == "PUT_YOUR_DISCORD_BOT_TOKEN_HERE":
        parser.error("Provide --discord-token, set DISCORD_TOKEN, or fill in settings.json")
    if not args.discord_user_id:
        parser.error("Set discord_user_id in settings.json or provide --discord-user-id")
    try:
        args.discord_user_id = int(args.discord_user_id)
        args.jobs = build_jobs(settings)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    if args.log_max_bytes <= 0:
        parser.error("log_max_bytes must be greater than zero")
    if args.log_backup_count < 0:
        parser.error("log_backup_count cannot be negative")
    return args


def main() -> None:
    args = parse_args()
    configure_logging(args)
    try:
        run_discord_bot(args)
    except KeyboardInterrupt:
        LOG.info("Shutdown requested")
    except Exception:
        # The supervisor will restart the process, but preserve the traceback
        # in the rotating log before allowing the process to exit.
        LOG.exception("Fatal bot error")
        raise


if __name__ == "__main__":
    main()
