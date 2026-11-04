; Inno Setup script for the Photo Importer installer. Built by packaging/build.ps1:
;   ISCC.exe /DAppVersion=1.0.0 packaging\installer.iss
; Installs per user (no administrator rights needed) into %LOCALAPPDATA%\Programs.
; Settings and the library index live in %APPDATA%\PhotoImporter and are kept on uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B1F3C2E-8F0B-4C55-9E6A-2D7C1A9B4E31}
AppName=Photo Importer
AppVersion={#AppVersion}
AppVerName=Photo Importer {#AppVersion}
DefaultDirName={autopf}\Photo Importer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=PhotoImporter-{#AppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\PhotoImporter.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove libraries from an older version before copying the new ones.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\exiftool"

[Files]
Source: "..\dist\PhotoImporter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Photo Importer"; Filename: "{app}\PhotoImporter.exe"
Name: "{autodesktop}\Photo Importer"; Filename: "{app}\PhotoImporter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PhotoImporter.exe"; Description: "{cm:LaunchProgram,Photo Importer}"; Flags: nowait postinstall skipifsilent
