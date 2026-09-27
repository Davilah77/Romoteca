# Romoteca

Romoteca is a safe and straightforward desktop inventory for ROM collections.
Load DAT catalogs, select your own folders and see which games are complete,
incomplete or missing without altering the collection.

![Romoteca](packaging/Romoteca.png)

![Romoteca collection scan](docs/romoteca-0.2.1.png)

## Features

- Read-only scanning: ROM files are never moved, renamed or deleted.
- Logiqx/ClrMamePro-style XML DAT catalogs.
- Multiple collections with a compact overview.
- Loose files and ZIP contents matched by SHA-1 or CRC32 and size.
- Automatic RetroBat/Batocera BIOS-folder detection with a manual override.
- Spanish and English interface.
- CHD, RAR and 7Z inventory without destructive extraction.
- CSV report export.
- Local DAT library. Third-party DAT files are not bundled.
- Optional online DAT discovery from official Redump HTTPS downloads.
- Community DAT Catalog support through HTTPS RAW files hosted on GitHub.

Romoteca is open-source software released under the MIT License.

## Run from source

Python 3.11 or later is required.

```powershell
py main.py
```

## Build the Windows executable

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The executable is created at `dist\Romoteca.exe`.
