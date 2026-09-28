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
- English, Spanish, French, German, Dutch and Russian interface.
- CHD, RAR and 7Z inventory without modifying the original collection.
- CHD content verification through the external MAME `chdman` tool.
- CSV report export.
- Local DAT library. Third-party DAT files are not bundled.
- Optional online DAT discovery from official Redump HTTPS downloads.
- Community DAT Catalog support through HTTPS RAW files hosted on GitHub.
- Configurable scan workers, light/dark theme and multilingual interface.
- Direct links to the official DAT database websites.
- Modified/translated file classification for common patch and translation markers.
- Configurable scan filters for scraped artwork, manuals, videos, metadata and other auxiliary files.
- Duplicate detection by SHA-1 or CRC/size, including equivalent BIN/CUE and CHD content.
- Clone-aware result filtering and clone parent details.
- Read-only ZIP inventory and optional RAR/7Z member listing through an installed 7-Zip executable.
- Persistent CHD result cache that stores only metadata and hashes.
- Light and dark themes, including the native Windows title bar.
- Read-only mode enabled by default, with an explicit setting before any future file-changing action.
- Local `logs` folder with scan, error and updater diagnostics.
- Local `backups` folder with timestamped configuration snapshots and restore support.

Romoteca is open-source software released under the MIT License.

## CHD support

CHD verification is optional and requires the external `chdman` executable from the [MAME project](https://www.mamedev.org/). Romoteca does not bundle `chdman`; select its location from **Settings → CHD tool…**. The tool is used read-only: Romoteca extracts each CHD to a temporary directory, hashes the virtual CUE/BIN tracks against the selected DAT, and removes the extracted files and directory when the scan finishes.

The first scan of a large CHD collection can take a while because the images have to be read and temporarily expanded. The time depends heavily on the storage device and the number and size of the images. Development and testing were performed on an 8 TB Seagate BarraCuda 5,400 RPM hard drive. Subsequent scans reuse a small metadata/hash cache stored in `%LOCALAPPDATA%\\Romoteca\\chd-cache.json`; extracted images are never kept in that cache. If a CHD is changed, moved or scanned with a different `chdman` executable, it is verified again.

CHD verification does not change, rename or delete any ROM. A CHD that is healthy but does not match the selected DAT is reported separately from a confirmed match. Translated or patched files are classified as **Modified / translated** when their names contain common translation or patch markers; the filename heuristic is not a substitute for a DAT hash match.

## Release 0.4.3

- Added CHD extraction and DAT matching through an externally selected `chdman` executable.
- Added persistent CHD metadata/hash caching for fast repeat scans.
- Improved cleanup of temporary CHD extraction folders.
- Added the Modified / translated result category and filter.
- Added native Windows title-bar colour refresh when switching themes.
- Expanded documentation and preservation-project acknowledgements.

## Release 0.4.3.1

- Fixed the Windows self-updater so it waits for the running executable to close completely before replacing and restarting it. This prevents PyInstaller `Python DLL` errors during updates.

## Release 0.4.3.2

- Replaced the updater's locale-sensitive process detection with a PowerShell PID wait and retry loop, preventing update races and temporary PyInstaller DLL errors on Windows.

## Release 0.4.3.3

- Added an explicit read-only safety mode enabled by default.
- Added local scan, error and updater logs next to the application.
- Added timestamped configuration backups and restore from the new `backups` folder.
- Hardened the Windows updater with staged replacement, SHA-256 verification, automatic rollback and a startup health check.

## Release 0.4.4

- Added configurable ignored extensions and directory filters for scraped auxiliary content.
- Added duplicate detection for files that share SHA-1 or CRC/size, including BIN/CUE and CHD equivalents.
- Added duplicate filtering and details showing the matching file.
- Improved clone handling with a clone-only filter and parent information.
- Added read-only RAR/7Z member inventory through an optional 7-Zip executable.

## Application data folders

Romoteca keeps operational files easy to find next to the executable:

- `dats`: imported and downloaded DAT catalogs.
- `logs`: rotating scan, error and update logs.
- `backups`: timestamped configuration backups. Restoring one keeps a backup of the current settings first.

ROM folders and BIOS folders are only scanned. Romoteca does not move, rename or delete their files.

## Scan filters and archives

The **Settings → Scan filters…** dialog controls ignored extensions and directory names. Ignored files are skipped before hashing and do not appear as unrecognized entries; the defaults cover common scraped manuals, videos, artwork and metadata folders. The filters are stored in the normal configuration and can be backed up or restored.

ZIP files are inspected with Python's standard library. RAR and 7Z files can be listed read-only when `7z.exe` or `7zz.exe` is installed and discoverable; the executable can also be selected from **Settings → Archive tool…**. Romoteca never rewrites or deletes an archive. If no compatible tool is available, the archive is reported as an unverified container instead of being treated as a verified ROM.

## Acknowledgements

Romoteca gratefully acknowledges the preservation work of [Redump](https://redump.info/), [No-Intro](https://www.no-intro.org/) and [TOSEC](https://www.tosecdev.org/). Their databases and DAT files are maintained by their respective communities and are not bundled with Romoteca. Please consult each project's own terms when downloading or using their data.

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

## Linux

Build a portable Linux binary with:

```bash
bash build_linux.sh
```

The resulting `dist/Romoteca-linux-x86_64.tar.gz` contains the executable. GitHub Actions also builds this asset automatically for tagged releases.
