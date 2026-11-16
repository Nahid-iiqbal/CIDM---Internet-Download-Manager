# Changelog - CIDM (Custom Internet Download Manager)

All notable changes to **CIDM** are documented in this release note.

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
