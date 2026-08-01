# EpgToXml

EpgToXml is an Enigma2 plugin for Dreambox receivers with DreamOS/Newnigma2
(OE2.5/OE2.6) and Vu+ receivers with VTi 15 (OE2.0). It fetches EPG data from
one or more sources and imports it directly into the Enigma2 EPG cache. No
external EPGImport plugin is required — the import engine is embedded.

EPG sources are modular: each one is a self-contained provider module under
`Plugins/Extensions/EpgToXml/providers/`. Currently available:

- `HD+ EPG` — loads the HD+ TV-guide programme grid for its German channel
  line-up, with programme descriptions.
- `DAZN Live-TV` — loads the DAZN live-schedule for DAZN's linear channels.
- `ARD EPG` — loads the ARD program grid, including regional subchannels
  (e.g. BR/WDR local variants), with programme descriptions where available.
- `ZDF EPG` — loads the ZDF program grid (ZDF, ZDFneo, ZDFinfo, 3sat, KI.KA,
  PHOENIX, arte) with programme descriptions.
- `Red Bull TV` — loads the EPG for Red Bull's 9 linear channels (World of Red Bull,
  Padel, Bike, Adventure, Motorsports, Surfing, Skateboarding, Winter, Action Reel).
  No channel-discovery API exists upstream; the channel list is maintained in
  `providers/redbull_tv.py` (`REDBULL_TV_CHANNELS`).
- `RTL+ EPG` — loads the RTL+ programme grid (RTL, VOX, RTLZWEI, NITRO, ntv,
  RTLup, VOXup, Super RTL and others) with programme descriptions, using
  anonymous guest authentication against the Bedrock platform API.
- `Teleboy.ch (Schweiz)` — loads the Teleboy programme grid for its 310 Swiss,
  German, French, Italian and other-language channels, with full programme
  descriptions. Limited to 4 days to keep the load on Teleboy's API low.

Neither requires HAR files, browser exports, or external Python packages.
Adding a further source means adding a new provider module; the task model,
UI, and XMLTV generation are provider-agnostic.

## Requirements

- Dreambox with DreamOS/Newnigma2 on OE2.5 or OE2.6, or
- ARM-based Vu+ receiver with VTi 15 on OE2.0
- Python 2.7 on the receiver
- Network access from the receiver to the selected EPG source(s)

Dreambox packages use Debian packaging and include the required
`python-sqlite3` dependency. Vu+/VTi packages use OPKG and the embedded importer
uses the classic `epg_new.dat` path instead of DreamOS's SQLite `epg.db` path.

## Install

Build both package formats:

```sh
python tools/build_deb.py
python tools/build_ipk.py
```

### Dreambox (DreamOS/Newnigma2 OE2.5/OE2.6)

Install the Debian package:

```sh
scp dist/*.deb root@dreambox:/tmp/
ssh root@dreambox "dpkg -i /tmp/enigma2-plugin-extensions-epgtoxml_*.deb"
```

### Vu+ (VTi 15/OE2.0)

Install the OPKG package:

```sh
scp dist/*.ipk root@vuplus:/tmp/
ssh root@vuplus "opkg install /tmp/enigma2-plugin-extensions-epgtoxml_*.ipk"
```

Restart the Enigma2 GUI after installation. Neither package restarts the GUI
automatically.

## Usage

Open `EpgToXml` from the plugin menu.

- Green creates a new task.
- Yellow or OK edits the selected task.
- Blue starts a manual import for the selected task.
- MENU opens the settings menu (debug logging, import routine).

The settings menu offers:

- `Debug-Logging` enables verbose logging to `/var/log/epgtoxml.log`.
- `Import-Routine` controls which EPG import path the engine uses:
  - `Standard (A dann B)` — auto-detects: tries `importEvents`/`importEvent` first, falls back to `epgdat` (default).
  - `Routine A (importEvents)` — forces the in-memory import API and reports an error if the required patch is absent.
  - `Routine B (epgdat)` — forces the `epg.db`/`epg_new.dat` file-based import.
- `Globale Importzeit 1/2` defines up to two daily default import times used by
  every task that has its schedule set to `Globalen Standard verwenden` (see below).

Inside a task:

- `Quelle` selects the EPG source (HD+, DAZN, ARD, ZDF, Red Bull TV, RTL+, or
  Teleboy.ch) and its channel.
- `Zielsender` selects the receiver service from the channel list.
- `Tage laden` defaults to `3` and is limited to `14`, except for Teleboy.ch
  which is limited to `4`.
- `EPG danach importieren` controls whether the EPG is imported into the receiver after data generation.
- `Zeitplan` chooses how the task is scheduled:
  - `Globalen Standard verwenden` — follows the global default import times set in
    the settings menu (default for new tasks).
  - `Eigene Zeiten` — reveals `Tägliche Importzeit 1/2` to set up to two daily
    scheduled imports just for this task, independent of the global default.
  - `Deaktiviert` — the task never runs automatically, even if a global default
    is configured.
- `Task löschen` removes the task.

Manual imports run in a separate progress window. Scheduled imports run in the
normal GUI/standby session; deep-standby wakeup is not part of this release.

## Files On The Receiver

- `/etc/epgtoxml/tasks.json`
- `/etc/epgtoxml/settings.json`
- `/etc/epgtoxml/import/epgtoxml.channels.xml`
- `/etc/epgtoxml/import/epgtoxml.sources.xml`
- `/tmp/epgtoxml/output/<task-id>.xml`
- `/var/log/epgtoxml.log`
- `/var/log/epgtoxml.log.1`

The files under `/tmp/epgtoxml/output/` are internal temporary XML source files.
They are regenerated for each import and may disappear after a reboot.

On upgrade from 0.5.0 or 0.5.1, existing `/media/hdd/epgtoxml/tasks.json` and
`/media/hdd/epgtoxml/settings.json` are copied to `/etc/epgtoxml` if the new
files do not exist yet. The old files are intentionally left in place.

Tasks saved before the global default schedule was introduced keep their exact
prior behaviour (their own times, or no automatic schedule) — they are never
silently switched to the global default. Only newly created tasks default to
following it.

## Development

Run local tests:

```sh
python -m pytest
```

Compile-check the plugin:

```sh
python -m py_compile Plugins/Extensions/EpgToXml/*.py Plugins/Extensions/EpgToXml/providers/*.py
```

Build the Debian package:

```sh
python tools/build_deb.py
```

Build the VTi OPKG package:

```sh
python tools/build_ipk.py
```

## License

GNU General Public License v2 (GPLv2). Copyright (c) 2026 Arcardy.

EpgToXml embeds the EPG import engine derived from the EPGImport plugin
(`enigma2-plugin-extensions-epgimport`), which is licensed under the GPLv2.
Because GPLv2 is a copyleft license, the combined work is distributed under
the GPLv2. See `LICENSE` for the full text and `NOTICE` for attribution.
