# Operations and troubleshooting

## First-time setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .\settings.example.json .\settings.json
notepad .\settings.json
```

Fill in the Plex and Discord credentials, then start with:

```text
start_plex_playlist_discord_bot.bat
```

The start script uses `.venv\Scripts\python.exe` when available and otherwise
falls back to `python.exe` on `PATH`.

## Normal operation

The batch file returns immediately because the bot and supervisor run hidden.
Confirm operation in the dated log file, for example:

```text
logs\plex_playlist_watcher-2026-09-12.log
```

Healthy startup includes messages for Discord gateway connection and each
configured job's `Watching ...` line. A processed file should produce queued,
batch, scan, found, added, sorted, and Discord notification activity.

The configured `log_file` is a base name. The bot adds the startup date before
the extension, so `logs\plex_playlist_watcher.log` produces a file such as
`logs\plex_playlist_watcher-2026-09-12.log`. Size-based rotation uses the same
dated basename and appends `.1` through the configured backup count.

## Stop and restart

Use:

```text
stop_plex_playlist_discord_bot.bat
start_plex_playlist_discord_bot.bat
```

Starting alone also performs the stop step first. PID files and the stop
sentinel are runtime artifacts and are ignored by Git.

## Troubleshooting

### The start file says packages are missing

Install into the same interpreter the launcher will use:

```powershell
python -m pip install -r requirements.txt
```

If a virtual environment exists, activate it first. The launcher preflight
checks imports for `discord.py`, `PlexAPI`, and `watchdog`.

### The bot is online but a video is not processed

Check the log for:

- The job's `Watching` line.
- A queued event or `Discovery found new file` line.
- The exact Plex-visible path in the warning.
- A Plex scan request and indexing timeout.

Verify that the file extension is configured, the file is still present, and
`plex_library_folder` matches the path Plex reports. A file already present at
startup is intentionally ignored.

### Plex indexes the file but the playlist does not change

Confirm that `playlist` names a regular playlist, not a smart playlist, and
that the configured Plex token can edit it. The log should show `Added ...`
and `Sorted playlist ...` after successful indexing.

If the configured regular playlist was deleted, the bot recreates it from the
first successfully indexed batch. Look for `Recreated missing regular playlist`
in the log.

### Discord DMs are not arriving

Verify `discord_token` and numeric `discord_user_id`. The bot does not need
server channel permissions or privileged intents, but it must be able to
resolve the configured user and Discord must permit the DM. Inspect the log
for the Discord exception; a DM failure does not stop Plex watching.

### Files added during sleep

The periodic discovery fallback defaults to 30 seconds after wake. Look for a
`Discovery found new file` entry. Lower `folder_poll_seconds` if quicker
detection is needed, at the cost of more directory enumeration.

### Watched folder was deleted and recreated

If the bot remains running, periodic discovery detects the recreated folder
within the configured `folder_poll_seconds` interval (30 seconds by default).
Files found after the original startup baseline are processed. The Watchdog
event subscription may not resume for the recreated directory, so this polling
fallback is what guarantees recovery.

If the bot starts while the folder is missing, startup fails until the folder
exists. Files already present when the bot eventually starts are intentionally
ignored as startup files.

### Playlist was deleted

If a configured playlist is missing, the bot waits until a video is indexed,
then recreates it as a regular playlist using that batch. It subsequently
sorts the playlist according to `sort_by`. A smart playlist with the configured
name is still rejected because Plex does not support the required reorder
operation.

### Discord stays offline after sleep

After a suspend/resume gap of about one minute, the bot detects that Discord's
gateway heartbeats were interrupted and forces a gateway reconnect. Look for
`Detected a ... system/event-loop gap`, followed by either `Discord gateway
session resumed` or a fresh `Discord bot logged in as ...` message. The
filesystem watchers remain running during this reconnect.

## GitHub safety

Keep these local-only artifacts uncommitted:

- `settings.json`
- `logs/`
- `*.pid`
- `*.stop`
- `.venv/`

The committed `settings.example.json` contains placeholders only.
