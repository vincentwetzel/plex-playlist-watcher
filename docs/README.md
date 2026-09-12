# Project documentation

This project is a local Discord-controlled-notification service for Plex
folder workflows. The Discord bot does not control Plex; it reports successful
playlist additions while the local watcher performs the Plex operations.

## Documents

- [Architecture and behavior](architecture.md) — event flow, batching,
  sleep recovery, and sorting guarantees.
- [Configuration reference](configuration.md) — global settings and the
  multi-job `jobs` array.
- [Operations and troubleshooting](operations.md) — installation, launch,
  shutdown, logs, and common failures.

The [root README](../README.md) is the quickest getting-started guide.
