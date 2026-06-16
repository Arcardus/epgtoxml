# EpgToXml 0.6.0

EpgToXml is an Enigma2 plugin for Dreambox/Newnigma2 OE2.5 receivers. It fetches
Sky.de EPG data and imports it directly into the Enigma2 EPG cache. No external
EPGImport plugin is required — the import engine is embedded.

The current provider is `Sky.de EPG`. It loads the Sky channel list directly and
does not require HAR files, browser exports, or external Python packages.

## Requirements

- Dreambox with OE2.5 / DreamOS, tested on Newnigma2
- Python 2.7 on the receiver (`python-sqlite3` is pulled in automatically by the package)
- Network access from the receiver to Sky.de

## Install

Build the package:

```sh
python tools/build_deb.py
```

Copy the generated package to the receiver and install it:

```sh
scp dist/enigma2-plugin-extensions-epgtoxml_0.6.0_all.deb root@dreambox:/tmp/
ssh root@dreambox "dpkg -i /tmp/enigma2-plugin-extensions-epgtoxml_0.6.0_all.deb"
```

Restart the Enigma2 GUI after installation. The package does not restart the GUI
automatically.

## Usage

Open `EpgToXml` from the plugin menu.

- Green creates a new task.
- Yellow or OK edits the selected task.
- Blue starts a manual import for the selected task.
- MENU toggles debug logging.

Inside a task:

- `Quelle` selects the EPG source and Sky.de channel.
- `Zielsender` selects the receiver service from the channel list.
- `Tage laden` defaults to `3` and is limited to `14`.
- `EPG danach importieren` controls whether the EPG is imported into the receiver after data generation.
- `Tägliche Importzeit 1/2` enables up to two daily scheduled imports.
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

## License

GNU General Public License v2 (GPLv2). Copyright (c) 2026 Arcardy.

EpgToXml embeds the EPG import engine derived from the EPGImport plugin
(`enigma2-plugin-extensions-epgimport`), which is licensed under the GPLv2.
Because GPLv2 is a copyleft license, the combined work is distributed under
the GPLv2. See `LICENSE` for the full text and `NOTICE` for attribution.
