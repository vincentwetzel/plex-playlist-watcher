# Plex playlist folder watcher

Runs a local Discord bot that watches configured folders for completed video
files, asks Plex to scan each folder, adds newly indexed videos to its paired
regular Plex playlist, sorts each playlist by its configured order, and sends
a DM about each batch.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create your private settings file from the safe template:

```powershell
Copy-Item .\settings.example.json .\settings.json
notepad .\settings.json
```

Put your Plex token in `settings.json`. That file is listed in `.gitignore` and
will not be committed. Also fill in the Discord bot token and your numeric
Discord user ID. The supplied example shows several independent jobs. Replace
all of the `YOUR_LOCAL_*_FOLDER` placeholders with actual folders on your
machine:

```powershell
python .\plex_playlist_watcher.py
```

Once `settings.json` is filled in, you can use the batch files instead:

```text
start_plex_playlist_discord_bot.bat
stop_plex_playlist_discord_bot.bat
```

The start file performs a visible preflight check before launching the hidden
supervisor. It verifies that `settings.json` exists and that the selected
Python interpreter can import `discord.py`, `PlexAPI`, and `watchdog`. If one
is missing, it prints the installation command and exits instead of silently
restarting a broken bot.

The start file first runs the stop routine, waits for existing processes to
terminate, clears the stop signal, and then launches one hidden PowerShell
supervisor. The supervisor runs the bot from `.venv` when available and
restarts it after an unexpected crash. The stop file prevents that restart and
stops the matching bot process.

The bot writes timestamps, watcher activity, Plex scan/indexing progress,
playlist operations, Discord connection events, and errors to
`logs/plex_playlist_watcher-YYYY-MM-DD.log`. Logs rotate automatically at 5
MiB, with the five previous files retained as `.1` through `.5`. Configure
this globally in `settings.json` if desired:

```json
{
  "log_file": "logs/plex_playlist_watcher.log",
  "log_max_bytes": 5242880,
  "log_backup_count": 5
}
```

Relative log paths are resolved from the project directory. The current date
is added to the configured log filename when the bot starts; rotated files
retain that dated name. Log files are ignored by Git, so they are available
locally for debugging without entering the repository.

Every job watches its configured folder, allows files to finish copying,
scans them into its configured Plex library, adds them to its paired regular
playlist, sorts according to `sort_by`, and reports the additions in a Discord
DM. The default is `duration`, which sorts shortest-first; use
`"sort_by": "creation_date"` to sort oldest-first by Plex's Date Added value.
Only files created or moved into a watched folder after the bot starts are
processed. Files already present at startup are ignored.

In addition to live filesystem events, each job periodically checks for newly
appeared video paths. This fallback helps recover files added while Windows or
the watcher was suspended during sleep. The startup baseline is still ignored,
so enabling this fallback does not turn startup into a playlist import. The
default discovery interval is 30 seconds and can be changed globally with
`folder_poll_seconds` or overridden on an individual job.

The Discord gateway has a separate sleep-recovery monitor. If the event loop
was suspended for about one minute, the bot refreshes the gateway connection
after wake while keeping the filesystem watchers and their startup baselines
alive. See the [operations guide](docs/operations.md#discord-stays-offline-after-sleep)
for the relevant log messages.

For deeper project documentation, see the [documentation index](docs/README.md),
including [architecture](docs/architecture.md),
[configuration](docs/configuration.md), and
[operations/troubleshooting](docs/operations.md).

## Adding monitored folder/playlist pairs

Add another object to the `jobs` array. Global timing and behavior settings
apply to every job, while a job can override them when needed:

```json
{
  "name": "YouTube",
  "watch_folder": "YOUR_LOCAL_YOUTUBE_FOLDER",
  "library": "YOUTUBE",
  "playlist": "YOUTUBE",
  "sort_by": "creation_date"
}
```

Only these three job fields are required:

- `watch_folder`: the local folder to monitor.
- `library`: the Plex library to scan.
- `playlist`: the regular Plex playlist to update.

`plex_library_folder` and `plex_scan_path` are optional. If omitted, both
default to `watch_folder`, which is the correct setup when Plex runs on the
same Windows machine and sees the same path.

`sort_by` is optional and defaults to `duration`, sorting shortest videos
first. Set it to `creation_date` to sort oldest-first by Plex's Date Added
(`addedAt`) value. If the configured playlist is deleted, the bot recreates a
regular playlist automatically when the next video is indexed.

Each job is independent: a new file in one folder is scanned only in that
job's library, added only to that job's playlist, and reported with the job
name in the DM. The bot can run any number of jobs from the same settings
file.

The playlist must be a regular playlist, not a smart playlist. The script
also accepts command-line overrides, for example
`--plex-token your-token`, but do not put secrets in committed files.

## Important path detail

For each job, `watch_folder` is the path visible to the computer running this
script. If Plex Media Server runs in Docker or on a NAS and sees a different
path, set the optional `plex_library_folder` and `plex_scan_path` values. For
example:

```json
{
  "name": "Example Videos",
  "watch_folder": "YOUR_LOCAL_VIDEO_FOLDER",
  "plex_library_folder": "/plex/media/example_videos",
  "plex_scan_path": "/plex/media/example_videos",
  "library": "Example Videos",
  "playlist": "Example Videos"
}
```

The watcher waits for a file's size and modification time to stop changing,
then waits for Plex to expose the exact file path before adding it. Press
`Ctrl+C` to stop it.

## Discord setup

The bot only needs to log in and send you direct messages. It does not read
messages, post in server channels, manage users, or modify server settings.

### 1. Create the Discord application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications)
   and select **New Application**.
2. Give the application a name, such as `Plex Playlist Watcher`.
3. Open the **Bot** page and select **Add Bot**.
4. Under the bot's token section, select **Reset Token** if necessary, then
   copy the token. Treat it like a password. Do not paste it into source code,
   screenshots, chat, or a Git commit. Discord's documentation also warns that
   bot tokens are highly sensitive credentials.

### 2. Use the minimum install permissions

On the application's **Installation** page, configure the **Guild Install**
settings as follows:

- OAuth2 scope: `bot`
- Bot permissions: **No permissions** (permission value `0`)

Do not select `Administrator`, `View Channel`, `Send Messages`, `Read Message
History`, or any management permission. This bot sends messages through a DM
channel, so it does not need permission to read or write any server channel.
The `applications.commands` scope is also unnecessary because this project
does not define Discord commands.

Copy the generated install link, open it in a browser, and add the bot to a
small server that you control and share with your Discord account. The person
installing a bot into a server needs the appropriate server-management access,
normally **Manage Server**. Discord explains the relationship between install
scopes and bot permissions in its [OAuth2 and Permissions guide](https://docs.discord.com/developers/platform/oauth2-and-permissions).

### 3. Leave privileged intents disabled

On the **Bot** page, leave all privileged gateway intents disabled, including:

- Presence Intent
- Server Members Intent
- Message Content Intent

The program uses `discord.Intents.none()` and does not process Discord events
other than connection readiness. This is the least-privileged configuration
for this use case; `discord.py` still requires an explicit intents object when
creating the client. See the [discord.py client documentation](https://discordpy.readthedocs.io/en/latest/api.html).

### 4. Set the notification recipient

1. In the Discord desktop or browser client, open **User Settings → Advanced**
   and enable **Developer Mode**.
2. Right-click your own username or avatar and select **Copy User ID**.
3. Put the copied numeric value in the ignored `settings.json` file:

```json
{
  "discord_token": "paste-the-bot-token-here",
  "discord_user_id": 123456789012345678
}
```

Do not quote `discord_user_id`; it should be a number. Keep the rest of the
settings file's `jobs` configuration intact.

### 5. Start and test it

Start the bot with:

```text
start_plex_playlist_discord_bot.bat
```

The bot should appear online in the server. Copy a small test video into one
of the configured `watch_folder` locations. After the file is stable, the bot
will scan Plex, add the item to its paired playlist, sort the playlist, and DM
the configured user.

The bot does not need to receive a message first, but adding it to a shared
server makes the account easy to resolve. If Discord refuses the DM, check
that you have not blocked the bot and that your server privacy settings allow
direct messages from server members. The bot's local log will report a failed
DM without stopping the folder watchers.

If Plex's automatic library scanning is already enabled for a particular job,
set its `scan` value to `false`:

```json
{
  "name": "Example Videos",
  "watch_folder": "YOUR_LOCAL_VIDEO_FOLDER",
  "library": "Example Videos",
  "playlist": "Example Videos",
  "scan": false
}
```
