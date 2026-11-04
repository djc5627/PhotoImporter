# Changelog

All notable changes to Photo Importer. Each version's section becomes the notes of its [GitHub release](https://github.com/djc5627/PhotoImporter/releases).

## [1.3.0] - 2026-11-04

### Added
- **Photos grouped by day.** Thumbnails sit under a header for each day they were taken, newest day first, showing the date and how many of that day's photos are selected, e.g. *Tuesday, October 20, 2026 · 5 photos · 4 selected*. Click a header to select every photo from that day, or to deselect them all if they already are. A round tick on the header shows whether all, some or none of the day is selected.

## [1.2.0] - 2026-11-04

More room for your photos.

### Added
- **Thumbnail size slider** (Small / Medium / Large) on the grid toolbar; Ctrl+scroll over the photos does the same, and your choice is remembered. Large uses the camera's bigger embedded preview so it stays sharp.
- **The window remembers its size and position**, including being maximised. The first time it opens at 1280×900, centred, which fits a 1080p screen.

### Changed
- **Thumbnails fill the whole width.** A row gets another column once at least half of one more photo fits, and the tiles resize slightly so the row ends exactly at the edge. This updates as you resize the window.
- **Include menu:** the four *Include…* ticks under the grid are now one *Include* menu on the grid toolbar, with a count for each kind of skipped photo. The button shows how many kinds you've included, e.g. *Include (1)*.
- **Camera dropdown** on the grid toolbar replaces the camera table. It only appears when the card has photos from more than one camera. The import confirmation still lists each camera's folders and counts.
- **Compact top:** Library, Import into and Import from are plain rows instead of boxed sections.
- **Footer:** a shorter summary that is cut off with … (full text on hover) instead of widening the window, and a blue Import button.

### Fixed
- A rare freeze while thumbnails were loading.

## [1.1.0] - 2026-11-04

### Added
- **Choose photos one by one.** Click a thumbnail to select or deselect it; selected photos have a blue border and the rest are dimmed. Only selected photos are imported. New photos start out selected. A RAW+JPG pair is selected (and imported) together.
- **Shift-click** selects every photo from the last one you clicked to the one you Shift-click. **Select all** / **Select none** buttons (and Ctrl+A) act on the photos shown, and Space toggles the current photo. Double-click still opens a photo.
- **Delete photos from the SD card.** *Delete…* (or the Delete key) removes the selected photos shown from the card, after asking you to confirm how many. Nothing in your library is touched. SD cards have no Recycle Bin, so each photo is first copied to a *Deleted from card* folder on your PC and that copy is sent to the Windows Recycle Bin; restoring it from there puts it back in that folder, not on the card. A photo only leaves the card once its copy is safely in the Recycle Bin. Deleting is unavailable while importing.
- **Import confirmation** listing, for each camera, where its photos go and how many of each kind will be copied (New, Recently deleted, Deleted, Probably deleted, Imported again), with totals. It warns when some of the photos being imported aren't in the current view (Import copies every selected photo on the card, not just the ones shown) and lists what isn't being imported.
- **All on card** view, now the default: every photo on the card, each with a coloured label for its status (New, Recently deleted, Deleted, Probably deleted, Already imported). A **Selected for import** view shows just what will be copied.
- **Allow re-importing photos already in the library**: off by default. Already-imported photos can always be selected (for example to delete them from the card), but they're only imported again when this is on. The command line has `--include-imported` for the same.

### Changed
- Thumbnails are sorted newest first, so new photos are at the top.
- The *Include* ticks for deleted photos now select or deselect every photo in that group, and show as partly ticked when you've changed some by hand.
- The Import button says how many photos and files will be copied, e.g. *Import 42 photos (68 files)*.

## [1.0.0] - 2026-11-04

First release.

### Importing
- Finds the photos on an SD card (or any folder) that aren't in your photo library yet and copies them into a dated folder (`2026.11.04 Description`) or an existing folder, sorted into per-camera `jpg` and `raw` subfolders.
- Recognises photos already in the library by camera, file name and capture time, including ones copied by hand before the app existed. Existing folders, including older `M.D.YYYY Description` ones that Capture One links to, are never renamed, moved or changed.
- Safe copying: files are copied to a temporary name, checked and then renamed; an interrupted import picks up where it left off; a different photo with the same name is saved alongside (`R0001_1.JPG`) instead of overwriting.

### Deleted photos
- Photos you delete from the library (e.g. in Capture One) aren't offered again. They're shown in three groups, each skipped unless you tick *Include*:
  - **Recently deleted:** newer than any photo from that camera still in the library (e.g. an import folder you just deleted).
  - **Deleted:** older deletions the app has seen.
  - **Probably deleted:** older than your newest photo from that camera, for deletions made before the app was installed.

### Cards and cameras
- Inserting an SD card starts the search automatically.
- The first time a camera's photos are imported, the app asks which folders to use, pre-filled from where that camera's photos already are in your library.

### Preview
- Thumbnails of the photos before importing, with RAW+JPG pairs shown once. Look through any group (e.g. *Recently deleted*), filter by camera, and double-click to open a photo.

### Settings
- Library folder, date format for new folders, automatic search on card insert, ExifTool location, update check, and each camera's name and folders.

### Installing and updating
- Windows installer (no admin rights needed) with ExifTool included, plus a portable zip.
- The app tells you when a new version is available. Install it by running the new installer; your settings and library index are kept.
