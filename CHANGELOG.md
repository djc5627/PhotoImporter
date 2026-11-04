# Changelog

All notable changes to Photo Importer. Each version's section becomes the notes of its [GitHub release](https://github.com/djc5627/PhotoImporter/releases).

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
