# Changelog - CIDM (Chaos Internet Download Manager)

All notable changes to **CIDM** are documented in this release note.

---

## [v1.0.2] - 2026-11-17

### 🚀 Highlights & New Features

- **🔄 Automated In-App Update Engine (`updater.py`):**
  - Direct integration with GitHub Releases API (`Nahid-iiqbal/CIDM---Internet-Download-Manager`).
  - Seamless semantic versioning checks comparing current running app version with latest remote GitHub release tag.
  - Non-blocking background worker threads (`UpdateCheckWorker`, `UpdateDownloadWorker`) with live progress tracking, byte counters, and download speed estimation.
  - **1-Click Self-Update & Restart:**
    - **Installed App:** Automatically downloads `CIDM_Setup.exe` and runs automated silent upgrade (`/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /SUPPRESSMSGBOXES`), smoothly replacing files in `{app}` and relaunching CIDM.
    - **Portable App:** Automatically downloads portable archive, extracts files, and runs self-terminating background updater script that syncs the portable folder and restarts `CIDM.exe`.
  - Rich **Update Notification Dialog (`UpdateAvailableDialog`)** displaying new version tag, release title, and scrollable Markdown changelog notes pulled directly from the GitHub release body.

- **⚙️ Dedicated "Updates" Settings Tab:**
  - Added full update configuration pane in CIDM Settings:
    - Current installed version and release channel status.
    - `☑ Automatically check for updates on startup (recommended)`.
    - `☑ Automatically download updates in the background and notify when ready to restart`.
    - **"Check for Updates Now"** button with live status feedback.
    - Quick link to view all releases on GitHub.
  - Added **"Check for Updates..."** action to the right-click Windows system tray menu.

---

### 🎨 UI Refinements & Polish

- **Streamlined Status Bar:**
  - Removed internal bridge label (`Bridge: 127.0.0.1:9632`) from the bottom status bar for a clean, distraction-free footer displaying download count, speed limiter control, and total bandwidth speed.
- **Focused Navigation Bar:**
  - Streamlined the top toolbar by keeping update management consolidated in Settings and the system tray.

---

### 📦 Release Assets (v1.0.2)

| Asset Name | Description | Size |
| :--- | :--- | :--- |
| **`CIDM_Setup.exe`** | Windows Setup Installer with built-in auto-updater support | ~76 MB |
| **`CIDM_Portable_Windows_x64_v1.0.2.zip`** | Standalone portable build (No installation required) | ~103 MB |
| **`CIDM_Chrome_Extension_v1.0.2.zip`** | Manifest V3 extension package for Chromium browsers | ~28 KB |
| **`CIDM_Firefox_Extension_v1.0.2.xpi`** | Mozilla Firefox signed/unpacked add-on package (`.xpi`) | ~28 KB |
| **`CIDM_Firefox_Extension_v1.0.2.zip`** | Firefox extension archive | ~28 KB |

---

## [v1.0.1] - 2026-11-17

### 🚀 Highlights & New Features

- **🦊 Full Mozilla Firefox Extension Support (Manifest V3):**
  - Added native Gecko MV3 extension package (`firefox_extension/`) with `browser_specific_settings.gecko.id: "cidm-integration@cidm.github.com"`.
  - Implemented cross-browser `sessionStore` storage abstraction compatible with both Firefox and Chromium.
  - Supported Firefox download interception via `chrome.downloads.onCreated` and local HTTP JSON-RPC bridge (`127.0.0.1:9632`).
  - Automatic detection of Mozilla Firefox, Floorp, Zen, and Waterfox from Windows Registry (`App Paths\firefox.exe`) and standard 64-bit/32-bit install paths.
  - Guided 3-step activation walkthrough opening `about:debugging#/runtime/this-firefox` with automated 1-click clipboard copying of `manifest.json`.
  - Added Windows Registry auto-registration under `HKCU\Software\Mozilla\Firefox\Extensions`.

- **🎨 All-New Vector Brand Logo & Modern Visuals:**
  - Replaced legacy icons with a sleek dark squircle vector badge featuring a cyan-to-emerald gradient "C" ring and bold download arrow (`assets/cidm.svg`).
  - Generated high-resolution Windows `.ico` containing full mipmap scales (`256x256`, `128x128`, `64x64`, `48x48`, `32x32`, and `16x16`).
  - Rendered matching high-DPI extension icons (`icon16.png`, `icon32.png`, `icon48.png`, `icon128.png`) for both Chromium and Firefox.
  - Modernized application title, system tray icon, desktop drop target, and README headers.

- **📁 Reliable Extension Auto-Sync:**
  - Extension bundles are automatically copied and kept up-to-date in user profile directories on startup:
    - Chromium: `~/.cidm/extension/chromium/` (and `~/.cidm/extension/`)
    - Firefox: `~/.cidm/extension/firefox/`
  - Redesigned "Browser Integration" settings tab with side-by-side management and one-click path copying for both browser engines.

---

### 🛠️ Bug Fixes & Improvements

- **Fixed Missing Extension Files in Installed App:**
  - Resolved issue where `CIDM_Setup.exe` failed to copy extension source files to `{app}`. Both Chromium and Firefox extensions are now packaged directly into `{app}\extension\chromium` and `{app}\extension\firefox`.
  - Upgraded path resolution in `ui.py` (`get_extension_source_dir`) to check executable directories, PyInstaller temporary paths, and local source trees.

- **Fixed Installer Error 183 (`Cannot create a file when that file already exists`):**
  - Resolved a PyInstaller bundling quirk where `--add-data` previously generated `assets` as a plain file, preventing Windows from creating the `\assets\` folder.
  - Added `[InstallDelete]` rule `Type: files; Name: "{app}\assets"` to automatically delete any stale legacy file blocking folder creation.

- **Release Packaging Pipeline (`release.ps1`):**
  - Added automated build targets for Firefox Add-on packages (`CIDM_Firefox_Extension_v1.0.1.xpi` and `CIDM_Firefox_Extension_v1.0.1.zip`).
  - Updated Inno Setup installer script with bumped version metadata `1.0.1`.

---

### 📦 Release Assets (v1.0.1)

| Asset Name | Description | Size |
| :--- | :--- | :--- |
| **`CIDM_Setup.exe`** | Windows Setup Installer (Desktop shortcut, Start menu, Extension bundles) | ~79 MB |
| **`CIDM_Portable_Windows_x64_v1.0.1.zip`** | Standalone portable build (FFmpeg, Chromium & Firefox extensions included) | ~108 MB |
| **`CIDM_Chrome_Extension_v1.0.1.zip`** | Manifest V3 extension for Chrome, Edge, Brave, Opera, Vivaldi | ~28 KB |
| **`CIDM_Firefox_Extension_v1.0.1.xpi`** | Mozilla Firefox add-on package (`.xpi`) | ~28 KB |
| **`CIDM_Firefox_Extension_v1.0.1.zip`** | Firefox extension archive | ~28 KB |

---

## [v1.0.0] - 2026-11-17

### 🚀 Highlights & Major Features

- **Universal File Type Support:**
  Accelerate and download all file formats, including compressed archives (`.zip`, `.rar`, `.7z`, `.tar`, `.gz`), disk images (`.iso`), software installers (`.exe`, `.msi`, `.apk`, `.dmg`), documents (`.pdf`, `.docx`, `.xlsx`), audio (`.mp3`, `.flac`), and videos.

- **Dynamic Multi-Threaded Engine:**
  Segmented file downloading with up to 32 parallel connections, dynamic chunk redistribution, and automatic resume from `.cidm_state`.

- **Google Drive & Cloud File Normalization:**
  Automatic conversion of Google Drive view/share links (`/file/d/<id>/view`) and Dropbox links to high-speed direct download streams with automatic virus-scan bypass (`confirm=t`) and server `Content-Disposition` filename preservation.

- **Smart Filename Detection:**
  Fixed generic filename issues where cloud files defaulted to `download`. The engine intelligently inspects server headers, Content-Disposition, and browser tab titles to extract real file names (e.g. `2nd paper chapter 8 part 2.pdf`).

- **Media & Stream Acceleration:**
  Integrated streaming engine for YouTube, HLS (`.m3u8`), and DASH (`.mpd`) with bundled FFmpeg for automatic audio/video merging and soft/sidecar subtitle embedding.

- **Browser Integration Extension (v2.2.0):**
  Intercepts downloads in Chrome, Edge, and Brave using Chromium's `chrome.downloads.onDeterminingFilename` API. Includes in-page video overlay pill, context menu shortcuts ("Download with CIDM"), and a popup with Quick Download URL input.

- **Automated Extension Setup Wizard:**
  First-run detection guides users to install the extension directly to Chrome, Edge, or Brave with a single click, plus manual browser selection in Settings.

- **Power-User Network Features:**
  Multi-adapter NIC binding (combine Ethernet + Wi-Fi), configurable Proxy Pool with rotation, bandwidth speed limiter, and download scheduling with auto-shutdown.

- **One-Command Packaging Pipeline:**
  Added `release.ps1` and Inno Setup integration producing clean standalone installers, portable ZIPs, and extension packages.

---

### 📦 Release Assets

| Asset Name | Description | Size |
| :--- | :--- | :--- |
| **`CIDM_Setup.exe`** | Windows Setup Installer (Desktop shortcut, Start menu, Uninstaller) | ~76 MB |
| **`CIDM_Portable_Windows_x64_v1.0.0.zip`** | Standalone portable build (No installation required) | ~103 MB |
| **`CIDM_Chrome_Extension_v1.0.0.zip`** | Packed Chromium browser extension for Chrome, Edge, Brave | ~53 KB |

---

### 🛠️ Bug Fixes & Improvements

- **Fixed Google Drive Bad Request (400):** Exempted cloud hosts from `yt-dlp` media extraction to prevent `[GoogleDrive] HTTP Error 400: Bad Request`.
- **Fixed Taskbar Icon:** Set explicit `AppUserModelID` on Windows so CIDM displays its branded high-resolution icon in the taskbar.
- **Fixed Context Menu Filename:** Context menu on links now extracts the real target file name and extension rather than substituting the HTML page `<title>` or forcing `.mp4`.
- **Cleaned Packaging Dependencies:** Automatically bundles FFmpeg and adjacent codecs for clean out-of-the-box operation on any Windows machine.
