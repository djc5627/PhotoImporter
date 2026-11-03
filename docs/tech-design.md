# PhotoImporter — Tech Stack & Detailed Design Plan

## Context
Importing photos from multiple cameras' SD cards into a dated folder tree (`Pictures/2026.11.02 Halloween Hike/<camera>/{jpg,raw}`) is manual and error-prone, especially working out which photos on a card were already imported. See `docs/initial-design.md`.

Decisions so far:
- Python with a **PySide6** desktop UI.
- Copy only: no moving, deleting or formatting. Photos only, no videos.
- **Dedup by capture time + filename**, backed by a scan of the Pictures library cached in SQLite.
- **Auto-detect** inserted cards.
- **Summary + thumbnail preview** before copying.
- Capture One integration is out of scope. Capture One does not rename or move files, but it **does delete them** (e.g. during a cleanup). Photos deleted from the library must not be offered for import again (see *Deleted photos*).

## Tech stack
| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | You already know it. |
| UI | PySide6 (Qt 6) | Native folder dialogs, efficient thumbnail grids, worker threads. |
| Metadata | ExifTool via `pyexiftool` (stay-open batch mode) | Reliably reads ARW, CR2, CR3, DNG and JPG. Python EXIF libraries are unreliable on raws. Bundle `exiftool.exe`. |
| Index | SQLite (`sqlite3` stdlib) at `%APPDATA%\PhotoImporter\library.db` | Fast dedup lookups. Also stores cameras, settings and the import log. |
| Thumbnails | `QImageReader.setScaledSize` for JPGs; ExifTool `-PreviewImage`/`-JpgFromRaw` for raw-only shots | Fast, with no raw decoding. |
| Tooling | `uv` (env/deps), `ruff` (lint/format), `pytest` (+ `pytest-qt` later) | |
| Packaging | PyInstaller single-folder `.exe` (later milestone) | |

## Core concepts

**Photo identity (dedup key):** `(camera Model, filename, DateTimeOriginal [+ SubSecTimeOriginal], extension)`
- Store `DateTimeOriginal` as the raw EXIF string. Never convert it to a timezone-aware or UTC time; this avoids DST bugs.
- Fallback when a file has no EXIF date: file mtime. Explorer copies and `shutil.copy2` both preserve it.
- A raw and its JPG share filename and time, so the extension distinguishes them.

**File types:**
- JPG: `.jpg`, `.jpeg`
- Raw: `.dng .arw .cr2 .cr3 .nef .orf .raf .rw2 .pef`
- Everything else is ignored, including video and sidecar files.
- Whether a camera shoots raw is detected from what's on the card, not from stored config.

**Library index:**
- Walk the photos root, which defaults to `%USERPROFILE%\Pictures` and is configurable.
- Only photo extensions are indexed.
- Change detection is per file by `(path, size, mtime)`, read via `os.scandir`. Only new or changed files are read by ExifTool. Rows for files that no longer exist are moved to the deleted-photos history, not forgotten.
- If the photos root itself is missing (e.g. the drive is unplugged), the scan stops with an error instead of treating every photo as deleted.
- The first scan is slow, so it runs on a worker thread with a progress bar.

**Camera registry:**
- Keyed on EXIF `Make` + `Model`.
- Stores a nickname, the camera folder name (e.g. `ricoh`), and the JPG and raw subfolder names (default `jpg`/`raw`).
- When an unknown camera is found, a dialog asks for these, pre-filled from EXIF.

**Deleted photos:**
Each card photo falls into one of four groups:
1. **New:** imported.
2. **Already imported:** in the library now. Skipped.
3. **Deleted since import:** not in the library, but in the deleted-photos history. It was imported or indexed once, then deleted. Skipped unless the user ticks *Include*.
4. **Probably deleted earlier:** in neither, but its capture time is older than the newest library photo (current or deleted) from the same camera model. Covers photos deleted before the history existed. Skipped unless the user ticks *Include*. Photos with no EXIF capture time are never put here.

The UI always shows the counts for groups 3 and 4, so nothing is skipped silently. The CLI has `--include-deleted` and `--include-older`.

Limitation of group 4: if a camera's photos are imported out of date order (e.g. two cards used in rotation, and the newer card imported first), never-imported photos on the older card land here. Ticking *Include* imports them.

**Import target folder:**
- Create a new `YYYY.MM.DD <description>` folder (today's date, editable), **or** pick an existing one for a second import the same day.

## Architecture
```
src/photoimporter/
  core/            # pure Python, no Qt
    models.py      # dataclasses: PhotoFile, Camera, ImportPlan, PlanItem
    exif.py        # ExifTool wrapper (batch read of the tags needed)
    db.py          # SQLite schema + queries (files, cameras, settings, imports)
    indexer.py     # incremental library scan
    cards.py       # list removable drives that have DCIM; scan a card
    planner.py     # card files minus library index = ImportPlan grouped by camera/type
    copier.py      # safe copy and resumable execution of an ImportPlan
  cli.py           # dry-run / debug CLI: scan, plan, import
  ui/
    app.py, main_window.py
    workers.py     # QRunnable wrappers emitting progress/result signals
    card_watcher.py# QTimer polling drives for new DCIM volumes
    views/         # target-folder picker, plan summary, thumbnail grid, camera dialog, settings
tests/             # pytest for core; fixtures with sample files per camera
```

**DB tables:**
- `files(path PK, size, mtime, filename, ext, model, capture_time, subsec)`, indexed on `(model, filename, capture_time)`
- `deleted_files(path PK, filename, mtime, make, model, capture_time, subsec, deleted_at)`: files that disappeared from the library. Never pruned; a row is removed only if the file reappears at the same path.
- `cameras(make, model, nickname, folder_name, jpg_dir, raw_dir)`
- `settings(key, value)`
- `imports(id, started_at, target_dir, source)` and `import_files(import_id, src, dest, status)`

**Copy safety:**
- Copy to `name.part`, check the size, then rename. File timestamps are preserved via `shutil.copy2`.
- Never overwrite an existing file. An existing destination is skipped and logged.
- Each copied file is added to `files` immediately. An interrupted import therefore resumes cleanly, and a re-run is a no-op.

**Threading:** EXIF reads, thumbnail generation and copies all run on `QThreadPool` workers and report back through signals. Nothing slow runs on the GUI thread.

**Card detection:**
- Poll drive letters every ~2 s and look for a `DCIM` folder. Check whether `os.listdrives()` (Python 3.12+) fits; otherwise iterate drive letters.
- Limitation: a camera connected by USB in MTP mode has no drive letter and won't be detected. SD card readers work.

## UI flow
1. **Main window:**
   - Target folder bar: New (date + description) or Choose existing.
   - Cards panel: auto-detected cards, plus a "Browse…" fallback.
   - Library index status: last scan time and a Rescan button.
2. **Card inserted:**
   - Scan the card and run the planner.
   - Prompt to register any unknown camera.
3. **Preview:**
   - Summary per camera, e.g. "Ricoh GR III — 42 new (42 jpg, 42 raw), 310 already imported".
   - Thumbnail grid of the new photos. A raw+JPG pair shows one thumbnail with a RAW badge.
4. **Import:** progress bar, then a result summary. Then insert the next card and repeat into the same target folder.
5. **Settings:** photos root, date format, camera registry editor.

## Milestones
1. **Core engine + CLI (no Qt):**
   - Project setup (uv, ruff, pytest).
   - ExifTool wrapper, validated against a real file from each camera, to confirm tag names and the Canon format.
   - Indexer, planner, copier.
   - `photoimporter plan <card>` dry run, run against your real library to prove dedup.
2. **Minimal PySide6 UI:** target folder picker, manual card browse, plan summary, import with progress.
3. **Card auto-detect + camera registration dialog.**
4. **Thumbnail preview grid.**
5. **Settings screen + PyInstaller packaging** with a bundled `exiftool.exe`.

## Verification
- **Unit tests (pytest):**
  - Dedup key matching.
  - Planner grouping.
  - Copier temp-file/rename handling, skip-on-exists, and resume after a simulated crash.
  - Indexer incremental rescan.
- **Deleted-photo test:** import a card, delete one photo from the library, plan again. That photo must show as *deleted since import* and not be copied unless included.
- **Idempotency acceptance test:** import a card, then plan again. The second run must show **0 new**.
- **Legacy test:** run the planner against a card whose photos you previously copied by hand in Explorer. Those photos must be reported as already imported.
- **Interrupt test:** kill a copy mid-run, restart it, and confirm it completes without duplicates or `.part` leftovers.
- **Manual UI check:** insert real SD cards from each camera and confirm detection, the preview and the resulting folder tree.

## Assumptions (redirect if wrong)
- The photos root defaults to `%USERPROFILE%\Pictures`.
- The date format for new folders is `YYYY.MM.DD`, editable in settings.
- Older folders use `M.D.YYYY Description` and must never be renamed or moved: Capture One links to those paths. The app only reads library folders, never changes or deletes anything in them, and can import into an old folder as an existing folder. Duplicate detection goes by EXIF and filename, not folder names.
- Cards are formatted only when nearly full, not after each import, so a card usually holds photos from several earlier imports, including some later deleted from the library.
- Camera folder names are lowercase nicknames (e.g. `ricoh`, `sony rx100`).
- A single card only contains photos from one camera. Mixed cards still work, since grouping is per file.
