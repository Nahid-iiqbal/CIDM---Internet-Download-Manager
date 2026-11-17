# release.ps1 - One-Command Release Packaging Script for CIDM
param(
    [string]$Version = "1.0.1"
)

$ErrorActionPreference = "Stop"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "                CIDM Release Packager v$Version                  " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# Terminate running background CIDM processes locking files in dist/
Get-Process | Where-Object { $_.ProcessName -like "*cidm*" -or $_.ProcessName -like "*pyidm*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# Locate Python environment
$PythonExe = "python"
if (Test-Path ".venv\Scripts\python.exe") {
    $PythonExe = (Resolve-Path ".venv\Scripts\python.exe").Path
    Write-Host "[*] Using virtual environment Python: $PythonExe" -ForegroundColor Gray
} else {
    Write-Host "[*] Using system Python: $PythonExe" -ForegroundColor Gray
}

# Check for Inno Setup compiler (ISCC.exe)
$Iscc = Get-Command "iscc" -ErrorAction SilentlyContinue
if (-not $Iscc) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) {
            $Iscc = $cand
            break
        }
    }
}

# 1. Run build_app.py
if ($Iscc) {
    Write-Host "[+] Inno Setup compiler found: $Iscc" -ForegroundColor Green
    Write-Host "[*] Building PyInstaller distribution and Windows Installer..." -ForegroundColor Cyan
    & $PythonExe build_app.py --installer
} else {
    Write-Host "[!] Inno Setup (ISCC.exe) not found on PATH or standard locations." -ForegroundColor Yellow
    Write-Host "    To build CIDM_Setup.exe installer, install Inno Setup: winget install JRSoftware.InnoSetup" -ForegroundColor DarkGray
    Write-Host "[*] Building portable distribution package only..." -ForegroundColor Cyan
    & $PythonExe build_app.py
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Build failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

# Ensure Output directory exists
$OutputDir = Join-Path $PSScriptRoot "Output"
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

# 2. Package Portable Zip from dist\CIDM\*
$DistCidm = Join-Path $PSScriptRoot "dist\CIDM"
$PortableZip = Join-Path $OutputDir "CIDM_Portable_Windows_x64_v$Version.zip"

if (Test-Path $DistCidm) {
    Write-Host "`n[*] Creating Portable Zip: $PortableZip" -ForegroundColor Cyan
    if (Test-Path $PortableZip) {
        Remove-Item $PortableZip -Force
    }
    Compress-Archive -Path "$DistCidm\*" -DestinationPath $PortableZip -Force
    Write-Host "[+] Portable Zip created successfully." -ForegroundColor Green
} else {
    Write-Host "[!] Warning: Directory $DistCidm not found. Skipping portable zip." -ForegroundColor Yellow
}

# 3. Package Chrome Extension Zip from chrome_extension\*
$ExtDir = Join-Path $PSScriptRoot "chrome_extension"
$ExtensionZip = Join-Path $OutputDir "CIDM_Chrome_Extension_v$Version.zip"

if (Test-Path $ExtDir) {
    Write-Host "[*] Creating Chrome Extension Zip: $ExtensionZip" -ForegroundColor Cyan
    if (Test-Path $ExtensionZip) {
        Remove-Item $ExtensionZip -Force
    }
    Compress-Archive -Path "$ExtDir\*" -DestinationPath $ExtensionZip -Force
    Write-Host "[+] Chrome Extension Zip created successfully." -ForegroundColor Green
} else {
    Write-Host "[!] Warning: Directory $ExtDir not found. Skipping extension zip." -ForegroundColor Yellow
}

# 4. Package Firefox Extension XPI and Zip from firefox_extension\*
$FirefoxExtDir = Join-Path $PSScriptRoot "firefox_extension"
$FirefoxXpi = Join-Path $OutputDir "CIDM_Firefox_Extension_v$Version.xpi"
$FirefoxZip = Join-Path $OutputDir "CIDM_Firefox_Extension_v$Version.zip"

if (Test-Path $FirefoxExtDir) {
    Write-Host "[*] Creating Firefox Extension Package: $FirefoxZip" -ForegroundColor Cyan
    if (Test-Path $FirefoxZip) {
        Remove-Item $FirefoxZip -Force
    }
    Compress-Archive -Path "$FirefoxExtDir\*" -DestinationPath $FirefoxZip -Force

    if (Test-Path $FirefoxXpi) {
        Remove-Item $FirefoxXpi -Force
    }
    Copy-Item -Path $FirefoxZip -Destination $FirefoxXpi -Force
    Write-Host "[+] Firefox Extension XPI & Zip created successfully." -ForegroundColor Green
} else {
    Write-Host "[!] Warning: Directory $FirefoxExtDir not found. Skipping firefox extension packaging." -ForegroundColor Yellow
}

# 5. Summary Table of Artifacts
Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host "                  Release Artifacts Summary                      " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

$artifacts = Get-ChildItem -Path $OutputDir -File | Where-Object {
    $_.Name -like "*$Version*" -or $_.Name -like "CIDM_Setup*"
}

if ($artifacts) {
    $artifacts | Select-Object Name, @{
        Name = "Size";
        Expression = {
            if ($_.Length -ge 1MB) {
                "{0:N2} MB" -f ($_.Length / 1MB)
            } else {
                "{0:N2} KB" -f ($_.Length / 1KB)
            }
        }
    }, LastWriteTime | Format-Table -AutoSize
} else {
    Write-Host "No release artifacts found in $OutputDir." -ForegroundColor Yellow
}

# 5. Git and GitHub Release Commands
$ghArtifacts = ($artifacts | ForEach-Object { "Output\$($_.Name)" }) -join " "

Write-Host "-----------------------------------------------------------------" -ForegroundColor Gray
Write-Host "To publish this release to GitHub, run:" -ForegroundColor Green
Write-Host ""
Write-Host "  git tag -a `"v$Version`" -m `"Release v$Version`"" -ForegroundColor White
Write-Host "  git push origin `"v$Version`"" -ForegroundColor White
if ($ghArtifacts) {
    Write-Host "  gh release create `"v$Version`" $ghArtifacts --title `"CIDM v$Version`" --generate-notes" -ForegroundColor White
} else {
    Write-Host "  gh release create `"v$Version`" Output\* --title `"CIDM v$Version`" --generate-notes" -ForegroundColor White
}
Write-Host "-----------------------------------------------------------------" -ForegroundColor Gray
