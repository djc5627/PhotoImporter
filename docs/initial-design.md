# Photo Importer Initial Design

## Intro/Motivation
- I take photos with multiple camera models and then edit them with Capture One Pro on my Windows desktop
- Importing the photos from each SD card is tedious
- My goal is to speed up the creation of the folders and importing the photos into the correct folders

## My current process
- Navigate to my photos directory
- Create a folder with todays date and description
    - Ex. 2026.11.02 Halloween Hike
- Then, for each camera I need to:
    - Plugin in the SD card
    - Create a subfolder for the camera model (Ex. Ricoh)
    - Create a subfolder inside that one for jpg and raw (if raw images supported by camera)
    - Check my last import to see which image on the camera's sd card is the first one that is NOT already imported by a previous set of imports
    - Select all the images past that date that are NOT yet imported and add them to the newly created for jpg and do the same for raws
    - Remove SD card
- Open Capture One and import photos for editing

## Sample file structure for an import
- Pictures
    - 2026.11.02 Halloween Hike
        - canon
            - jpg
        - ricoh
            - jpg
            - raw
        - sony rx100
            - jpg
            - raw


## Requirments
- Be able to select/create working directory for new set of photo imports
- Point to directory of SD card or other import source and be able to
    - Detect the model of the camera (can probably leverage the metadata on the photo files like camera model)
    - Automatically detect which types of files the camera exports (raw, jpgs, etc)
    - Automatically scan my photo dump directory for files already imported from the camera so that we can just import the delta, not imported, images into the new directory and subfolders
- The tool should support
    - Storing "known" cameras and correlated those to the photo metadata. Support configuration like nickname for camera, desired output folder names, etc
    - Visual interface for these processes