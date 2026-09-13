# Configuration reference

Copy the safe template before editing:

```powershell
Copy-Item .\settings.example.json .\settings.json
```

`settings.json` is ignored by Git. Never commit Plex or Discord tokens.

## Global settings

| Setting | Required | Description |
|---|---:|---|
| `plex_url` | yes | Plex base URL, usually `http://127.0.0.1:32400`. |
| `plex_token` | yes | Plex authentication token. `PLEX_TOKEN` overrides it. |
| `discord_token` | yes | Discord bot token. `DISCORD_TOKEN` overrides it. |
| `discord_user_id` | yes | Numeric Discord ID receiving notification DMs. |
| `log_file` | no | Base log path; relative paths start at the project directory. The current date is added to the filename. |
| `log_max_bytes` | no | Rotation threshold; default is 5 MiB. |
| `log_backup_count` | no | Rotated files retained; default is 5. |
| `settle_seconds` | no | Required file stability period; default is 5. |
| `file_timeout` | no | Maximum wait for a file to stabilize; default is 3600 seconds. |
| `plex_timeout` | no | Maximum wait for Plex to index a file; default is 300 seconds. |
| `poll_interval` | no | Poll delay while waiting; default is 3 seconds. |
| `batch_seconds` | no | Time to collect nearby events; default is 8 seconds. |
| `folder_poll_seconds` | no | New-file discovery fallback interval; default is 30 seconds. |
| `scan` | no | Whether to request a Plex scan; default is `true`. |
| `sort_by` | no | Playlist order: `duration` (shortest first, default) or `creation_date` (oldest Plex Date Added first). |

## Job settings

`jobs` must be a non-empty array. Each job requires:

| Setting | Description |
|---|---|
| `name` | Optional label used in logs and Discord DMs. |
| `watch_folder` | Local folder monitored by the Windows watcher. |
| `library` | Plex library title to scan and search. |
| `playlist` | Regular Plex playlist title to update. |

These path overrides are optional:

| Setting | Default | Description |
|---|---|---|
| `plex_library_folder` | `watch_folder` | Root path as Plex reports it when matching indexed files. |
| `plex_scan_path` | `plex_library_folder` | Path sent to Plex for the library scan. |

For Plex running locally on Windows, a minimal job is enough:

```json
{
  "name": "Example Videos",
  "watch_folder": "YOUR_LOCAL_VIDEO_FOLDER",
  "library": "Example Videos",
  "playlist": "Example Videos"
}
```

For a local watcher and a differently mounted Plex server:

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

Jobs may override `extensions`, timing values, `folder_poll_seconds`, `scan`,
and `sort_by`. `creation_date` uses Plex's `addedAt` / Date Added value; items
without that value sort last. Startup files are always ignored; there is no
startup-import setting.
