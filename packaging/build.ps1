<#
.SYNOPSIS
    Builds the Windows app, a portable zip and (if Inno Setup is installed) the installer.

.DESCRIPTION
    Output goes to dist\:
      dist\PhotoImporter\                       the app folder (PhotoImporter.exe + exiftool)
      dist\PhotoImporter-<version>-portable.zip
      dist\PhotoImporter-<version>-setup.exe    needs Inno Setup 6 (https://jrsoftware.org/isinfo.php)

.PARAMETER ExifToolZip
    A Windows ExifTool zip (exiftool-<version>_64.zip) to bundle. Downloaded from exiftool.org
    when not given.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
param([string]$ExifToolZip = "")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

Invoke-Checked "uv sync" { uv sync --group build }
$Version = (uv run python -c "import photoimporter; print(photoimporter.__version__)").Trim()
Write-Host "Building Photo Importer $Version"

# 1. The app
Remove-Item -Recurse -Force dist\PhotoImporter -ErrorAction SilentlyContinue
Invoke-Checked "PyInstaller" {
    uv run pyinstaller packaging\photoimporter.spec --noconfirm --distpath dist --workpath build\pyinstaller
}

# 2. ExifTool, next to the app in dist\PhotoImporter\exiftool
New-Item -ItemType Directory -Force build | Out-Null
if (-not $ExifToolZip) {
    # The bundled version is pinned so builds are repeatable. To update ExifTool, change
    # packaging\exiftool-version.txt (latest: https://exiftool.org/ver.txt).
    $ExifVersion = (Get-Content packaging\exiftool-version.txt -Raw).Trim()
    $ExifToolZip = "build\exiftool-${ExifVersion}_64.zip"
    if (-not (Test-Path $ExifToolZip)) {
        Write-Host "Downloading ExifTool $ExifVersion"
        # exiftool.org hosts its Windows zips on SourceForge; exiftool.org itself is a fallback
        # (it only keeps the latest version).
        $Urls = @(
            "https://sourceforge.net/projects/exiftool/files/exiftool-${ExifVersion}_64.zip/download",
            "https://exiftool.org/exiftool-${ExifVersion}_64.zip"
        )
        :download foreach ($Attempt in 1..3) {
            foreach ($Url in $Urls) {
                try {
                    Invoke-WebRequest $Url -OutFile $ExifToolZip -UseBasicParsing -UserAgent "Wget" -TimeoutSec 120
                    break download
                } catch {
                    Write-Warning "Download from $Url failed (attempt $Attempt): $_"
                    Remove-Item -Force $ExifToolZip -ErrorAction SilentlyContinue
                }
            }
            Start-Sleep -Seconds (10 * $Attempt)
        }
        if (-not (Test-Path $ExifToolZip)) { throw "Could not download ExifTool $ExifVersion" }
    }
}
Remove-Item -Recurse -Force build\exiftool -ErrorAction SilentlyContinue
Expand-Archive $ExifToolZip build\exiftool
$ExifExe = Get-ChildItem build\exiftool -Recurse -Filter "exiftool(-k).exe" | Select-Object -First 1
if (-not $ExifExe) { throw "exiftool(-k).exe not found in $ExifToolZip" }
$Dest = "dist\PhotoImporter\exiftool"
New-Item -ItemType Directory -Force $Dest | Out-Null
# Renaming drops the "(-k)", which would otherwise make ExifTool wait for a key press.
Copy-Item $ExifExe.FullName "$Dest\exiftool.exe"
Copy-Item -Recurse (Join-Path $ExifExe.DirectoryName "exiftool_files") "$Dest\exiftool_files"
Invoke-Checked "ExifTool check" { & "$Dest\exiftool.exe" -ver }

# 3. Portable zip
$Zip = "dist\PhotoImporter-$Version-portable.zip"
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Compress-Archive dist\PhotoImporter $Zip

# 4. Installer
$Iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($Iscc) {
    Invoke-Checked "Inno Setup" { & $Iscc "/DAppVersion=$Version" packaging\installer.iss }
} else {
    Write-Warning "Inno Setup 6 not found, so no installer was built. The app is in dist\PhotoImporter."
}

Get-ChildItem dist -File | Format-Table Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
