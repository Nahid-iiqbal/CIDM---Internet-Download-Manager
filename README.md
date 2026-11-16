# CIDM — Custom Internet Download Manager

<div align="center">

![CIDM Logo](assets/cidm.ico)

**A high-performance, modern, multi-threaded download manager and video grabber for Windows.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-green?logo=qt)](https://www.qt.io/)
[![Extension](https://img.shields.io/badge/Extension-Manifest%20V3-orange?logo=googlechrome)](chrome_extension/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20x64-blue?logo=windows)](https://microsoft.com)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

</div>

---

## Overview

**CIDM** is an open-source, feature-complete internet download manager built with Python and PySide6. Engineered for maximum throughput, network resilience, and seamless desktop integration, CIDM accelerates downloads up to 10x by dynamically segmenting files across up to 32 parallel worker threads, bonding multiple network adapters, rotating proxy pools, and capturing streaming media directly from modern web browsers.

---

## Key Features

### 🚀 High-Speed Multi-Threaded Engine
- **Dynamic Connection Splitting:** Divides files into dynamic byte segments downloaded concurrently across 1–32 worker threads.
- **Real-Time Visual Segment Matrix:** Real-time visual progress bar tracking active chunks, buffered bytes, and completed segments for every download.
- **Robust Pause & Resume:** Full byte-range verification, persistent `.cidm_part` state journals, and zero-data-loss resume even after network disconnects or process termination.
- **Expired URL Refresh:** Right-click to refresh expired temporary authorization tokens or download URLs without losing existing progress.

### 🌐 Multi-Adapter Link Aggregation (Channel Bonding)
- **Multi-Interface Socket Binding:** Distribute worker threads across multiple physical network adapters simultaneously (e.g., Ethernet + Wi-Fi or 5G Mobile USB Tethering).
- **Same-Subnet Routing Detector:** Built-in subnet analyzer detects gateway metric conflicts and guides optimal interface balancing.

### 🛡️ Per-Worker Proxy Pool
- **Rate-Limit Bypass:** Cycle worker threads across pools of HTTP, HTTPS, and SOCKS5 proxies to bypass aggressive per-IP download rate limits.
- **Direct Fallback:** Optionally include direct connections within the proxy pool rotation.

### 🎬 Universal Video & Stream Grabber
- **Streaming Media Sniffer:** Built-in `yt-dlp` and `ffmpeg` engine capturing HLS (`.m3u8`), MPEG-DASH (`.mpd`), and direct MP4/WebM video streams.
- **Batch Sniffer:** Probe websites for all downloadable media assets with multi-resolution selector (4K, 1080p, 720p, audio-only).

### 🧩 Browser Extension & 1-Click Integration
- **Manifest V3 Extension:** Full integration with Google Chrome, Microsoft Edge, Brave Browser, Opera, and custom Chromium browsers.
- **First-Run Automatic Onboarding:** Detects installed browsers on launch, prepares the extension in `~/.cidm/extension/`, and provides a 1-click activation walkthrough.
- **Manual Browser Selector:** Settings tab to install the extension into any custom browser executable (`.exe`).
- **Download Interception:** Seamlessly passes browser download requests to CIDM via local HTTP bridge (`127.0.0.1:9632`).

### 🎛️ Modern, Compact UI
- **Dual Themes:** Clean, compact Dark Grey and Light themes with high-density table views and customizable column headers.
- **Categories & Auto-Sorting:** Automatically routes downloads into dedicated subfolders (`Compressed`, `Videos`, `Programs`, `Documents`, `Music`).
- **Scheduler & Queues:** Schedule start/stop times, set recurring schedules, and auto-shutdown, sleep, or hibernate when queues finish.
- **System Tray & Mini Drop Target:** Minimizes to the Windows system tray with clipboard monitoring and an optional floating desktop drop target.
- **Speed Limiter:** Global bandwidth throttling with popover control.

---

## Project Structure

```
idm2/
├── assets/                  # Icons and branding assets (cidm.ico, cidm.png)
├── chrome_extension/        # Manifest V3 browser integration extension
│   ├── background.js        # Service worker handling network requests & CIDM bridge
│   ├── content.js           # Media sniffer script injected into web pages
│   ├── manifest.json        # Extension manifest
│   ├── popup.html / popup.js# Extension popup control panel
│   └── icons/               # Extension icons
├── vendor/                  # Bundled tools (FFmpeg binary & DLLs)
│   └── bin/                 # ffmpeg.exe, ffprobe.exe
├── engine.py                # Core multi-threaded download engine & adapter binding
├── grabber.py               # Video streaming sniffer & extractor interface
├── main.py                  # Application entry point, single-instance mutex & tray
├── server.py                # Local HTTP JSON-RPC bridge server (port 9632)
├── ui.py                    # PySide6 desktop interface, themes, & dialogs
├── build_app.py             # PyInstaller packaging automation script
├── installer.iss            # Inno Setup 6 installer compilation script
├── release.ps1              # One-command release packager (Installer + Portable + Extension)
├── run.bat / cidm.bat       # Quick-launch batch scripts prioritizing local venv
├── requirements.txt         # Python package dependencies
└── .gitignore               # Git ignore rules for build outputs & artifacts
```

---

## Installation & Setup

### Prerequisites
- **Operating System:** Windows 10 or Windows 11 (64-bit recommended)
- **Python:** Python 3.10 or higher
- **FFmpeg (Optional but Recommended):** Place `ffmpeg.exe` into `vendor/bin/` or add it to system `PATH` for video grabbing.

### Quick Start (Running from Source)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/cidm.git
   cd cidm
   ```

2. **Create a virtual environment and install dependencies:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Launch CIDM:**
   ```powershell
   python main.py
   # Or simply double-click run.bat / cidm.bat
   ```

---

## Browser Extension Integration

CIDM captures browser downloads and video streams through its lightweight browser extension.

### First-Run Automatic Setup
When launching CIDM for the first time, an onboarding wizard automatically:
1. Syncs extension files to `~/.cidm/extension/`.
2. Registers extension keys in the Windows Registry for Chrome, Edge, and Brave.
3. Automatically copies the folder path to your clipboard.
4. Opens your browser to its extensions page (`chrome://extensions`, `edge://extensions`, `brave://extensions`).
5. Guides you through turning on **Developer mode** and clicking **Load unpacked** (press `Ctrl+V` to paste the path).

### Manual Setup via Settings
To install the extension into any other browser (e.g. Opera GX, Vivaldi, Thorium, or a portable browser):
1. Open CIDM and click **Settings** (or press the Settings icon in the sidebar).
2. Go to the **Browser Integration** tab.
3. Click **Browse (.exe)...** under *Add to Custom Browser of Your Choice* and select your browser's executable.
4. Click **Install Extension in Selected Browser**.

---

## Packaging & Building Releases

### One-Command Release Packaging (`release.ps1`)

CIDM includes a single-command PowerShell release script that compiles:
- The standalone Windows installer (`Output\CIDM_Setup.exe`) via Inno Setup.
- A portable `.zip` distribution (`Output\CIDM_Portable_Windows_x64_v1.0.0.zip`).
- A packaged Chrome Extension zip (`Output\CIDM_Chrome_Extension_v1.0.0.zip`).

To build:
```powershell
.\release.ps1 -Version "1.0.0"
```

*Note: If Inno Setup (`ISCC.exe`) is not installed, `release.ps1` will automatically build the portable distribution and provide instructions for installing Inno Setup via `winget install JRSoftware.InnoSetup`.*

### Manual PyInstaller Build

To build the portable directory distribution directly:
```powershell
python build_app.py
```
Output will be placed in `dist/CIDM/`.

To build the installer using Inno Setup directly:
```powershell
python build_app.py --installer
```

---

## Configuration & Storage

CIDM stores its settings and cached extension files in the user profile directory:
- **Settings:** `~/.cidm/settings.json`
- **Extension Files:** `~/.cidm/extension/`
- **Partials / Fragments:** Saved alongside downloads as `.cidm_part` journals until complete.

---

## License

This project is licensed under the [MIT License](LICENSE).
