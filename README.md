# PhotoImporter

Imports only the new photos from camera SD cards into dated, per-camera folders
(`2026.11.02 Halloween Hike/ricoh/jpg`, `.../ricoh/raw`). Design: [docs/tech-design.md](docs/tech-design.md).

## Install (Windows)

Download `PhotoImporter-<version>-setup.exe` from the
[latest release](https://github.com/djc5627/PhotoImporter/releases/latest) and run it. It installs
for your user only (no admin rights), adds Photo Importer to the Start menu (and optionally the
desktop), and bundles ExifTool. Your settings and library index are kept in
`%APPDATA%\PhotoImporter`, so they survive updates, reinstalling and uninstalling.

The `-portable.zip` holds the same app without an installer: unzip anywhere and run
`PhotoImporter.exe`.

**Updating:** the app shows a bar when a new version is out (turn this off in Settings). Click
*What's new & download*, run the new installer, and it replaces the old version in place. What
changed in each version is in [CHANGELOG.md](CHANGELOG.md) and on each release page.

## Releasing a new version

1. Set the new version in `src/photoimporter/__init__.py` (e.g. `1.0.1`).
2. Add a `## [1.0.1] - YYYY-MM-DD` section at the top of `CHANGELOG.md`.
3. Merge to `main`.

The **Test and build** workflow then builds and tests the installer and, because `v1.0.1`
hasn't been released yet, publishes the release (creating the `v1.0.1` tag), using the changelog
section as its notes. Pushes to `main` that don't change the version don't release anything.
A test fails if `CHANGELOG.md` has no section for the current version. Every push also builds
the installer as a downloadable workflow artifact.

To build locally instead: `powershell -ExecutionPolicy Bypass -File packaging\build.ps1` (needs
[uv](https://docs.astral.sh/uv/); the installer also needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)).

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and [ExifTool](https://exiftool.org) (`exiftool.exe` on
PATH, or `PHOTOIMPORTER_EXIFTOOL` set to its full path).

```
uv sync
uv run photoimporter config --root "D:\Photos"   # folder holding your dated import folders
uv run photoimporter scan                        # index existing photos (first run is slow)
```

## Use

Desktop app:

```
uv run photoimporter-gui
```

Insert an SD card and the app finds its new photos on its own. Photos already in your library,
and photos you deleted from it (e.g. in Capture One), are skipped; tick *Include* to import
deleted ones anyway. Photos deleted after your newest remaining photo from a camera (e.g. a
whole import folder you just deleted) have their own tick, separate from older culls.
Thumbnails of every photo on the card are shown newest first, each labelled New, Already
imported, Deleted and so on. Tick or untick photos to choose exactly what's imported; use *Show*
to look at one group, and select a camera to see only its photos. The first time
a camera's photos are imported, the app asks which folders to use, pre-filled from where that
camera's photos already are in your library.

Command line:

```
uv run photoimporter plan E:\ --new "Halloween Hike"       # dry run
uv run photoimporter import E:\ --new "Halloween Hike"     # copy new photos
uv run photoimporter import --target "D:\Photos\2026.11.02 Halloween Hike"   # next card, same folder
uv run photoimporter import E:\ --new "Trip" --include-deleted   # also re-import deleted photos
uv run photoimporter cameras
uv run photoimporter camera-set --make "SONY" --model "DSC-RX100M7" --nickname "RX100" --folder "sony rx100"
```

Run tests with `uv run pytest`.
