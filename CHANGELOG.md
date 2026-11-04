# Changelog

All notable changes to Photo Importer. Each version's section becomes the notes of its [GitHub release](https://github.com/djc5627/PhotoImporter/releases).

## [1.1.0] - 2026-11-04

### Added
- **Choose photos one by one.** Every thumbnail has a tick box; only ticked photos are imported. New photos start out ticked. A RAW+JPG pair shares one tick box and is imported together.
- **Tick all** and **Untick all** buttons for the photos shown, and **Space** flips the tick boxes of all selected thumbnails (select several with Shift- or Ctrl-click).
- **All on card** view, now the default: every photo on the card, each with a coloured label for its status (New, Recently deleted, Deleted, Probably deleted, Already imported). A **Ticked for import** view shows just what will be copied.
- **Allow re-importing photos already in the library**: off by default; when switched on, already-imported photos can be ticked to copy them again into the import folder. The command line has `--include-imported` for the same.

### Changed
- Thumbnails are sorted newest first, so new photos are at the top.
- The *Include* ticks for deleted photos now tick or untick every photo in that group, and show as partly ticked when you've changed some by hand.
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
