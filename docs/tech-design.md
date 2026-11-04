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
| Thumbnails | The thumbnail embedded in each file (ExifTool `-ThumbnailImage`, then `-PreviewImage` for RAWs without one), rotated by EXIF Orientation. JPGs with neither are decoded with `QImageReader.setScaledSize`. | Only a few KB per file are read from the card, and no RAW decoding. |
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
- When an unregistered camera has photos to import, a dialog asks for these on Import. They are pre-filled from the library: the camera folder and subfolders most often used by that camera model's photos in `<date>/<camera>/<subfolder>/<photo>` paths, falling back to the lowercase EXIF model and `jpg`/`raw`. This also matches cameras that were used before the app existed. The CLI uses the same suggestions without asking.

**Deleted photos:**
Each card photo falls into one of five groups:
1. **New:** imported.
2. **Already imported:** in the library now. Skipped.
3. **Recently deleted:** in the deleted-photos history, and its capture time is newer than the newest photo from the same camera model still in the library (or that camera has no photos left). Typically a just-deleted import folder. Kept apart from group 4 so it can be restored without bringing back every older cull. Skipped unless the user ticks *Include*.
4. **Deleted since import:** the rest of the deleted-photos history (imported or indexed once, then deleted). Photos without a capture time land here, never in group 3. Skipped unless the user ticks *Include*.
5. **Probably deleted earlier:** in neither, but its capture time is older than the newest library photo (current or deleted) from the same camera model. Covers photos deleted before the history existed. Skipped unless the user ticks *Include*. Photos with no EXIF capture time are never put here.

Each skipped group has its own tick in the *Include* menu, and the UI always shows their counts, so nothing is skipped silently. The CLI has `--include-recent-deleted`, `--include-deleted` and `--include-older`.

Limitation of group 5: if a camera's photos are imported out of date order (e.g. two cards used in rotation, and the newer card imported first), never-imported photos on the older card land here. Ticking *Include* imports them.

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
- Poll drive letters every ~2 s and look for a `DCIM` folder, via `os.listdrives()` (Python 3.12+) or by iterating drive letters. Only removable and fixed local drives are checked: probing a disconnected network drive can block for seconds.
- An inserted card (or one already in when the app starts) fills in the source and starts "Find new photos". If a task is running, the card is checked once it finishes. Removing the card clears its results.
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
   - A one-line summary in the footer; the per-camera breakdown is in the import confirmation.
   - Thumbnail grid, loaded in the background in small batches so the first tiles appear quickly. A RAW+JPG pair (same folder, name and capture time) is one tile marked `RAW+JPG`; a RAW-only shot is marked `RAW`.
   - A *Show* menu switches the grid between *All on card* (the default), *Ticked for import*, and each status group. Tiles are sorted newest first (capture time, else file date) and carry a coloured status label.
   - Tiles are chosen by highlighting: a click toggles a tile, Shift-click chooses the range from the last clicked tile, Ctrl+A/*Select all*/*Select none* act on the tiles shown, Space toggles the current tile, and double-click opens the photo (undoing its first click's toggle). Chosen tiles get a blue border, the rest are dimmed. The plan keeps the set of chosen card files (new photos at first); a RAW+JPG pair is chosen together. The group *Include* ticks choose a whole status group and show partial state. Import copies chosen photos, except already-imported ones unless *Allow re-importing photos already in the library* is on.
   - Import copies every chosen photo on the card, not only the ones shown. Before copying, a confirmation window (`planner.import_breakdown` + `ui/import_dialog.py`) shows per camera the target subfolders and the number of pictures (RAW+JPG pairs once) per status, only for statuses with photos, plus totals, a warning when some aren't in the current view, and what isn't being imported.
   - *Delete…* (or the Delete key) deletes the chosen photos *shown* from the card after a confirmation with the count. `core/deleter.py` copies each file to `%LOCALAPPDATA%\PhotoImporter\Deleted from card\<time>`, sends the copies to the Recycle Bin in one `SHFileOperationW` call (`FOF_ALLOWUNDO`, with a warning if something is too big to recycle), and only then removes the card file. Files whose copy couldn't be recycled stay on the card. Disabled while busy.
   - Tiles are grouped under a header row per day (capture date, else file date), newest day first. A header shows the date and how many of its photos are selected; clicking it selects the whole day, or deselects it when all are selected. Headers live in the same `QListWidget` as the tiles (full-width items, no fixed grid), so Shift-click ranges skip them.
   - The grid toolbar holds *Show*, a camera dropdown (only with several cameras), the *Include* menu and a *Size* slider (Small 120 / Medium 160 / Large 320 px wide; Ctrl+scroll; saved as `thumbnail_size`). Large asks ExifTool for `PreviewImage` first and keeps a separate cache. Tiles are fitted to the width: columns = whole tiles that fit, plus one if at least half of another does, then the tiles are resized so the columns fill the row; refitted 40 ms after resizing stops.
   - The window's geometry is saved on close (`window_geometry`); the first launch is 1280×900 centred, shrunk to fit the screen.
   - Thumbnail loading stops when an import starts, so it doesn't slow the copy.
4. **Import:** progress bar, then a result summary. Then insert the next card and repeat into the same target folder.
5. **Settings:** photos root, date format, camera registry editor.

## Milestones
1. **Core engine + CLI (no Qt):** Done.
   - Project setup (uv, ruff, pytest).
   - ExifTool wrapper, validated against a real file from each camera, to confirm tag names and the Canon format.
   - Indexer, planner, copier.
   - `photoimporter plan <card>` dry run, run against your real library to prove dedup.
2. **Minimal PySide6 UI:** target folder picker, manual card browse, plan summary, import with progress. Done.
3. **Card auto-detect + camera registration dialog.** Done.
4. **Thumbnail preview grid.** Done.
5. **Settings screen + PyInstaller packaging** with a bundled `exiftool.exe`. Done:
   - Settings window (General: library folder, new-folder date format, search on card insert, ExifTool location; Cameras: edit or forget registered cameras).
   - `packaging/build.ps1` builds the PyInstaller app folder, adds ExifTool (`dist\PhotoImporter\exiftool\exiftool.exe` + `exiftool_files`), a portable zip and an Inno Setup per-user installer. The GitHub Actions workflow runs the tests on Linux and Windows and publishes the installer as a build artifact.

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
- The date format for new folders is `YYYY.MM.DD`, editable in Settings (tokens `YYYY YY MM M DD D`).
- Older folders use `M.D.YYYY Description` and must never be renamed or moved: Capture One links to those paths. The app only reads library folders, never changes or deletes anything in them, and can import into an old folder as an existing folder. Duplicate detection goes by EXIF and filename, not folder names.
- Cards are formatted only when nearly full, not after each import, so a card usually holds photos from several earlier imports, including some later deleted from the library.
- Camera folder names are lowercase nicknames (e.g. `ricoh`, `sony rx100`).
- A single card only contains photos from one camera. Mixed cards still work, since grouping is per file.
