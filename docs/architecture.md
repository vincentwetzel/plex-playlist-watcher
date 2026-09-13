# Architecture and runtime behavior

## Components

The process contains one Discord client and one independent watcher per
configured job.

```text
Discord client
├── watcher: Example Videos
│   ├── Windows recursive filesystem observer
│   ├── periodic discovery fallback
│   └── Plex library + regular playlist
└── watcher: YouTube
    ├── Windows recursive filesystem observer
    ├── periodic discovery fallback
    └── Plex library + regular playlist
```

Each watcher has its own Plex connection, queue, event observer, library, and
playlist. A Discord notification callback is shared by the watchers and adds
the job name to each DM.

## New-file flow

1. The watcher establishes a baseline of supported video paths already in the
   folder. Those files are intentionally ignored.
2. Watchdog queues files created or moved into the folder. A periodic scan
   also queues paths first discovered after startup, which protects against
   missed Windows filesystem events during sleep.
3. Events arriving within `batch_seconds` are grouped.
4. Each candidate is checked until its size and modification time remain stable
   for `settle_seconds`. Stability checks run concurrently.
5. The watcher asks the configured Plex library section to scan
   `plex_scan_path`.
6. Plex is polled until each exact `plex_library_folder`-mapped file path is
   indexed and has a duration.
7. Items not already present in the paired playlist are added by rating key.
8. The entire regular playlist is reordered using Plex's move operation,
   shortest duration first. Missing durations sort last.
9. If at least one item was added, the Discord client sends a summary DM.

Events that arrive while a batch is being processed remain queued for the
next batch. If files arrive more than `batch_seconds` apart, they are handled
in separate batches; each batch still re-sorts the complete playlist.

## Sleep and wake behavior

The Python process and Discord connection may be suspended while Windows
sleeps. A small asyncio monitor detects a long event-loop gap after wake and
closes the stale gateway socket with a normal reconnect code. discord.py then
reconnects without stopping the watcher threads or rebuilding their startup
baselines. The watcher also performs periodic discovery, so files created
during sleep are detected after wake even if the original filesystem event was
lost. The monitor checks every 15 seconds and treats a gap of 60 seconds or
more as a suspend/resume event. Files present when the bot established its
baseline remain ignored.

## Process lifecycle

The start batch file runs a preflight check, stops any previous instance, and
starts the hidden PowerShell supervisor. The supervisor runs the Python bot,
records bot/supervisor PIDs, and restarts the bot after an unexpected exit.
The stop batch file writes a stop sentinel, terminates the recorded PIDs, and
prevents restart.
