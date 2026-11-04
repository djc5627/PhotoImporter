# PhotoImporter

Imports only the new photos from camera SD cards into dated, per-camera folders
(`2026.11.02 Halloween Hike/ricoh/jpg`, `.../ricoh/raw`). Design: [docs/tech-design.md](docs/tech-design.md).

## Setup

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
Thumbnails of the photos are shown before you import. Use *Show* to look through any group
(e.g. what's in *Recently deleted*), and select a camera to see only its photos. The first time
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
