# EpgToXml 0.5.0

EpgToXml is an Enigma2 plugin for Dreambox/Newnigma2 OE2.5 receivers. It fetches
Sky.de EPG data, prepares EPGImport-compatible files, and can start EPGImport
for the generated source.

The current provider is `Sky.de EPG`. It loads the Sky channel list directly and
does not require HAR files, browser exports, or external Python packages.

## Requirements

- Dreambox with OE2.5 / DreamOS, tested on Newnigma2
- Python 2.7 on the receiver
- Installed EPGImport plugin. Some OE2.5 images install it outside dpkg package
  tracking, so the release package recommends but does not hard-depend on the
  exact package name.
- Network access from the receiver to Sky.de

## Install

Build the package:

```sh
python tools/build_deb.py
```

Copy the generated package to the receiver and install it:

```sh
scp dist/enigma2-plugin-extensions-epgtoxml_0.5.0_all.deb root@dreambox:/tmp/
ssh root@dreambox "dpkg -i /tmp/enigma2-plugin-extensions-epgtoxml_0.5.0_all.deb"
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
- `EPGImport danach starten` controls whether EPGImport is started after data generation.
- `Tägliche Importzeit 1/2` enables up to two daily scheduled imports.
- `Task löschen` removes the task.

Manual imports run in a separate progress window. Scheduled imports run in the
normal GUI/standby session; deep-standby wakeup is not part of this release.

## Files On The Receiver

- `/media/hdd/epgtoxml/tasks.json`
- `/media/hdd/epgtoxml/settings.json`
- `/media/hdd/epgtoxml/output/<task-id>.xml`
- `/media/hdd/epgtoxml/epgtoxml-debug.log`
- `/media/hdd/epgtoxml/epgtoxml-debug.log.1`
- `/etc/epgimport/epgtoxml.channels.xml`
- `/etc/epgimport/epgtoxml.sources.xml`

The generated source also remains selectable in EPGImport if automatic triggering
is not possible on a specific image.

## Development

Run local tests:

```sh
python -m unittest discover -s tests
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

MIT License. Copyright (c) 2026 Arcardy.
