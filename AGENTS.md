# Agent and contributor instructions

## Project purpose

This is a Windows 11 Python service that watches one or more local folders,
scans newly arrived videos into Plex, adds them to paired regular Plex
playlists, sorts those playlists by duration, and sends Discord DMs.

## Source of truth

- Main implementation: `plex_playlist_watcher.py`
- Safe configuration template: `settings.example.json`
- Private runtime configuration: `settings.json` (ignored; never commit it)
- Windows lifecycle wrappers: `start_plex_playlist_discord_bot.bat`,
  `stop_plex_playlist_discord_bot.bat`, and
  `supervise_plex_playlist_discord_bot.ps1`
- Dependency declarations: `requirements.txt`
- Project documentation: `docs/`

## Behavioral invariants

Preserve these unless the user explicitly asks to change them:

1. Startup files are ignored. Only files created, moved into, or discovered
   after startup are processed.
2. `watch_folder`, `library`, and `playlist` are the required fields for each
   job. Plex path overrides are optional.
3. A playlist must be a regular playlist because smart playlists cannot be
   reordered through the supported API.
4. Duplicate playlist entries are avoided using Plex rating keys.
5. The complete playlist is sorted shortest-to-longest after each successful
   batch.
6. Credentials must come from ignored settings or environment variables, never
   source code, committed examples, logs, or command output.
7. The Discord bot uses the least-privileged empty intent set and only sends
   configured-user DMs.

## Development rules

- Use `apply_patch` for source and documentation edits.
- Keep Windows paths and PowerShell quoting in mind when changing launcher
  files.
- Do not print or inspect secret values from `settings.json`.
- Prefer small, testable changes. Avoid changing the Plex or Discord behavior
  merely to improve internal structure.
- Preserve the rotating log configuration when adding new diagnostics.

## Validation

At minimum, run:

```powershell
python -c "from pathlib import Path; compile(Path('plex_playlist_watcher.py').read_text(encoding='utf-8'), 'plex_playlist_watcher.py', 'exec')"
python -c "import json; json.load(open('settings.example.json', encoding='utf-8'))"
```

For behavior changes, also test with multiple jobs and multiple files in one
batch. Do not start the real bot during automated validation unless the user
explicitly requests it; doing so can modify Plex playlists and send Discord
messages.

See [`docs/architecture.md`](docs/architecture.md),
[`docs/configuration.md`](docs/configuration.md), and
[`docs/operations.md`](docs/operations.md) for more detail.
