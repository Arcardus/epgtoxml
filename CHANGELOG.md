# Changelog

## 0.6.0 - 2026-06-16

- Embedded the EPGImport import engine (`epgimport_engine/`) so no external
  EPGImport plugin is required anymore. Both import routines are supported:
  `eEPGCache.importEvents()`/`importEvent()` and the epg.db SQLite / epg.dat fallback.
- Removed the dependency/integration with the external EPGImport plugin; the EPG
  import now runs in-process from `plugin.py`.
- Moved the generated source/channel files to `/etc/epgtoxml/import`.
- Renamed the task option to "EPG danach importieren" and reworded the UI status texts.
- Relicensed the plugin to GPLv2 (the embedded engine is GPLv2). See `LICENSE` and `NOTICE`.

## 0.5.2 - 2026-06-14

- Moved persistent task and settings files to `/etc/epgtoxml`.
- Moved the rotating debug log to `/var/log/epgtoxml.log`.
- Kept generated EPGImport programme files under `/tmp/epgtoxml/output`.
- Added best-effort migration from `/media/hdd/epgtoxml/tasks.json` and
  `/media/hdd/epgtoxml/settings.json` without deleting old files.

## 0.5.1 - 2026-06-14

- Improved Sky.de network, DNS and SSL error messages.
- Moved internal generated EPGImport programme files to `/tmp/epgtoxml/output`.
- Kept task settings and debug logs persistent under `/media/hdd/epgtoxml`.

## 0.5.0 - 2026-06-13

- First releasable Dreambox/Newnigma2 OE2.5 build.
- Added task-based EPG profiles with selectable Sky.de source channel and selectable receiver target service.
- Added direct Sky.de EPG retrieval without HAR files.
- Added EPGImport source generation and automatic EPGImport start/monitoring.
- Added manual import progress screen and GUI/standby scheduler.
- Added rotating debug log under `/media/hdd/epgtoxml/epgtoxml-debug.log`.
- Added Debian package build for OE2.5/DreamOS receivers.
