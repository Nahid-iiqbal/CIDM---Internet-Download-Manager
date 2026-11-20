"""
updater.py - Automated Update Manager for CIDM (Chaos Internet Download Manager).

Features:
- Queries GitHub Releases API for the latest release tag and metadata.
- Compares semantic versioning between installed version and remote release.
- Provides non-blocking background QThread workers for checking and downloading updates.
- Supports seamless silent/interactive updates for both Installed (Inno Setup) and Portable modes.
- Fallback release page browser launcher.
"""
from __future__ import annotations

import os
import re
import sys
import time
import zipfile
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

import requests
from PySide6.QtCore import QObject, QThread, Signal

APP_VERSION = "1.0.3"
GITHUB_REPO = "Nahid-iiqbal/CIDM---Internet-Download-Manager"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_HTML_URL = f"https://github.com/{GITHUB_REPO}/releases"


def parse_version(v: str) -> tuple:
    """Extract semantic version components (major, minor, patch, build, is_final, prerelease)."""
    s = str(v).strip()
    # Check if there is an explicit version tag like v1.2.0 or standard semver X.Y.Z
    m_v = re.search(
        r"v(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?",
        s,
        re.IGNORECASE,
    )
    if m_v:
        m = m_v
    else:
        m = re.search(
            r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?", s
        )

    if not m:
        m_simple = re.search(r"(\d+)", s)
        return (int(m_simple.group(1)) if m_simple else 0, 0, 0, 0, 1, "")

    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3)) if m.group(3) is not None else 0
    build = int(m.group(4)) if m.group(4) is not None else 0
    prerelease = m.group(5) or ""
    # SemVer 2.0.0: Normal final release has higher precedence than any pre-release
    is_final = 0 if prerelease else 1
    return (major, minor, patch, build, is_final, prerelease)


def is_newer_version(latest_tag: str, current_version: str = APP_VERSION) -> bool:
    """Check if latest_tag represents a strictly newer version than current_version."""
    p_l = parse_version(latest_tag)
    p_c = parse_version(current_version)
    # Core numerical version comparison (major, minor, patch, build)
    if p_l[:4] != p_c[:4]:
        return p_l[:4] > p_c[:4]
    # If core numbers are equal: final release (1) > pre-release (0)
    if p_l[4] != p_c[4]:
        return p_l[4] > p_c[4]
    # Both are pre-releases: lexicographical comparison
    return p_l[5] > p_c[5]


@dataclass
class ReleaseAsset:
    name: str
    url: str
    size: int
    content_type: str = ""


@dataclass
class UpdateInfo:
    version: str
    tag_name: str
    title: str
    body: str
    html_url: str
    published_at: str
    installer_asset: Optional[ReleaseAsset] = None
    portable_asset: Optional[ReleaseAsset] = None
    all_assets: List[ReleaseAsset] = field(default_factory=list)

    @property
    def display_notes(self) -> str:
        """Clean markdown release notes without excess noise."""
        return self.body.strip() if self.body else "No release notes provided."

    @property
    def preferred_asset(self) -> Optional[ReleaseAsset]:
        """Return installer asset for installed apps, or portable for standalone."""
        if is_running_frozen() and not is_installed_app() and self.portable_asset:
            return self.portable_asset
        return self.installer_asset or self.portable_asset or (self.all_assets[0] if self.all_assets else None)


def check_for_update(
    current_version: str = APP_VERSION, timeout: float = 6.0
) -> Optional[UpdateInfo]:
    """Synchronously query GitHub API for the latest release. Raises on network/HTTP errors."""
    headers = {
        "User-Agent": f"CIDM-AutoUpdater/{current_version}",
        "Accept": "application/vnd.github.v3+json",
    }
    resp = requests.get(RELEASES_API_URL, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub API returned HTTP {resp.status_code}")
    data = resp.json()
    tag = data.get("tag_name", "")
    if not tag:
        raise ValueError("GitHub release contains no tag_name")

    # Check if newer
    if not is_newer_version(tag, current_version):
        return None  # Up to date

    assets = []
    inst_asset = None
    port_asset = None
    for a in data.get("assets", []):
        ra = ReleaseAsset(
            name=a.get("name", ""),
            url=a.get("browser_download_url", ""),
            size=int(a.get("size", 0)),
            content_type=a.get("content_type", ""),
        )
        assets.append(ra)
        name_lower = ra.name.lower()
        if "setup" in name_lower and name_lower.endswith(".exe"):
            inst_asset = ra
        elif "portable" in name_lower and name_lower.endswith(".zip"):
            port_asset = ra

    return UpdateInfo(
        version=tag.lstrip("vV"),
        tag_name=tag,
        title=data.get("name", tag),
        body=data.get("body", ""),
        html_url=data.get("html_url", RELEASES_HTML_URL),
        published_at=data.get("published_at", ""),
        installer_asset=inst_asset,
        portable_asset=port_asset,
        all_assets=assets,
    )


class UpdateCheckWorker(QThread):
    """Background thread to query GitHub Releases API."""

    update_available = Signal(object)  # UpdateInfo
    up_to_date = Signal(str)           # current_version
    check_failed = Signal(str)         # error message

    def __init__(
        self,
        current_version: str = APP_VERSION,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        try:
            update = check_for_update(self.current_version)
            if update:
                self.update_available.emit(update)
            else:
                self.up_to_date.emit(self.current_version)
        except Exception as e:
            self.check_failed.emit(str(e))


class UpdateDownloadWorker(QThread):
    """Background thread to download update package with progress reporting."""

    progress = Signal(int, int, int, float)  # percent, downloaded_bytes, total_bytes, speed_kbps
    completed = Signal(str)                 # local_file_path (avoids shadowing QThread.finished)
    finished = completed                    # backwards-compatibility alias
    failed = Signal(str)                    # error message
    cancelled = Signal()                    # user-initiated cancellation

    def __init__(
        self,
        asset_url: str,
        target_filename: str,
        expected_size: int = 0,
        expected_sha256: str = "",
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.asset_url = asset_url
        self.target_filename = target_filename
        self.expected_size = expected_size
        self.expected_sha256 = expected_sha256.strip().lower()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        # Validate asset URL to ensure it originates from official GitHub Release endpoints
        try:
            parsed = urllib.parse.urlparse(self.asset_url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not (
                host == "github.com"
                or host.endswith(".github.com")
                or host.endswith(".githubusercontent.com")
            ):
                self.failed.emit(f"Untrusted download host: {host}")
                return
        except Exception as e:
            self.failed.emit(f"Invalid download URL: {e}")
            return

        temp_dir = os.path.abspath(os.path.join(tempfile.gettempdir(), "cidm_update"))
        os.makedirs(temp_dir, exist_ok=True)

        # Sanitize filename to prevent directory traversal or writing outside temp_dir
        safe_name = os.path.basename(str(self.target_filename or "")).strip()
        safe_name = re.sub(r'[\/\\:*?"<>|]', '_', safe_name).strip()
        if not safe_name:
            safe_name = "CIDM_Update.exe"
        dest_path = os.path.abspath(os.path.join(temp_dir, safe_name))
        if not dest_path.startswith(temp_dir):
            dest_path = os.path.join(temp_dir, "CIDM_Update.exe")

        headers = {
            "User-Agent": f"CIDM-AutoUpdater/{APP_VERSION}",
            "Accept": "*/*",
        }

        hasher = hashlib.sha256()

        try:
            with requests.get(
                self.asset_url, headers=headers, stream=True, timeout=20.0
            ) as r:
                r.raise_for_status()
                total_size = int(r.headers.get("content-length", 0)) or self.expected_size
                downloaded = 0
                start_time = time.time()
                last_time = start_time

                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if self._is_cancelled:
                            f.close()
                            try:
                                os.remove(dest_path)
                            except Exception:
                                pass
                            self.cancelled.emit()
                            return

                        if chunk:
                            f.write(chunk)
                            hasher.update(chunk)
                            downloaded += len(chunk)

                            now = time.time()
                            if now - last_time >= 0.1 or downloaded == total_size:
                                elapsed = now - start_time
                                speed_kbps = (
                                    (downloaded / 1024.0) / elapsed
                                    if elapsed > 0
                                    else 0.0
                                )
                                pct = (
                                    int((downloaded / total_size) * 100)
                                    if total_size > 0
                                    else 0
                                )
                                self.progress.emit(
                                    pct, downloaded, total_size, speed_kbps
                                )
                                last_time = now

            if self._is_cancelled:
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
                self.cancelled.emit()
                return

            if self.expected_size > 0 and downloaded != self.expected_size:
                try:
                    os.remove(dest_path)
                except Exception:
                    pass
                self.failed.emit(
                    f"Size verification failed: expected {self.expected_size} bytes, got {downloaded} bytes."
                )
                return

            if self.expected_sha256:
                actual_sha = hasher.hexdigest().lower()
                if actual_sha != self.expected_sha256:
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                    self.failed.emit(
                        f"Checksum verification failed (SHA-256 mismatch)."
                    )
                    return

            self.completed.emit(dest_path)
        except Exception as e:
            if not self._is_cancelled:
                self.failed.emit(str(e))


def is_running_frozen() -> bool:
    """Check whether application is packaged with PyInstaller."""
    return getattr(sys, "frozen", False)


def is_installed_app() -> bool:
    """Check whether application was installed via Inno Setup."""
    if not is_running_frozen():
        return False
    app_dir = os.path.dirname(os.path.abspath(sys.executable))
    return os.path.exists(os.path.join(app_dir, "unins000.exe"))


def apply_update_and_restart(downloaded_file: str, silent: bool = True) -> bool:
    """Apply the downloaded update file and restart the application."""
    if not os.path.isfile(downloaded_file):
        return False

    is_exe = downloaded_file.lower().endswith(".exe")
    is_zip = downloaded_file.lower().endswith(".zip")

    # Mode 1: Installer Executable (Preferred for Inno Setup or standalone upgrade)
    if is_exe:
        try:
            args = [downloaded_file]
            if silent:
                # Inno Setup switches:
                # /SILENT /CLOSEAPPLICATIONS: cleanly terminates CIDM and runs upgrade
                # /RESTARTAPPLICATIONS: relaunches CIDM after finishing
                # /SP-: skips the 'This will install...' prompt
                # /SUPPRESSMSGBOXES: suppresses message boxes
                args.extend([
                    "/SILENT",
                    "/CLOSEAPPLICATIONS",
                    "/RESTARTAPPLICATIONS",
                    "/SP-",
                    "/SUPPRESSMSGBOXES",
                ])
            # Launch detached process
            if sys.platform == "win32":
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(
                    args,
                    creationflags=DETACHED_PROCESS,
                    close_fds=True,
                )
            else:
                subprocess.Popen(args)
            return True
        except Exception:
            return False

    # Mode 2: Portable ZIP archive upgrade
    elif is_zip and is_running_frozen():
        try:
            target_app_dir = os.path.dirname(os.path.abspath(sys.executable))
            extract_temp = os.path.join(
                tempfile.gettempdir(), "cidm_portable_extract"
            )
            if os.path.exists(extract_temp):
                import shutil
                shutil.rmtree(extract_temp, ignore_errors=True)
            os.makedirs(extract_temp, exist_ok=True)

            with zipfile.ZipFile(downloaded_file, "r") as z:
                z.extractall(extract_temp)

            # Check if extracted root contains CIDM/ subfolder or direct files
            source_content_dir = extract_temp
            inner_cidm = os.path.join(extract_temp, "CIDM")
            if os.path.isdir(inner_cidm):
                source_content_dir = inner_cidm

            # Generate a safe batch script to overwrite files once current process exits
            bat_path = os.path.join(
                tempfile.gettempdir(), "cidm_portable_updater.bat"
            )
            exe_target = os.path.join(target_app_dir, "CIDM.exe")

            bat_content = f"""@echo off
chcp 65001 >nul
echo Updating CIDM Portable...
timeout /t 2 /nobreak >nul
robocopy "{source_content_dir}" "{target_app_dir}" /E /IS /IT /NP /NJH /NJS /R:3 /W:1
if errorlevel 8 (
    echo [ERROR] CIDM Portable update failed to copy files.
    echo Please make sure CIDM is completely closed and try again.
    pause
    exit /b 1
)
start "" "{exe_target}"
timeout /t 1 /nobreak >nul
(goto) 2>nul & del "%~f0"
exit
"""
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=DETACHED_PROCESS,
                close_fds=True,
            )
            return True
        except Exception:
            return False

    return False
