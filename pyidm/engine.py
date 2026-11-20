"""
engine.py - Multi-threaded, resumable HTTP download engine.

Features
  * Forwards optional Cookie / User-Agent / Referer headers on every HEAD and GET.
  * Probes the server (HEAD, with a ranged-GET fallback) for size, range support
    and filename (Content-Disposition, falling back to the URL basename).
  * Segmented download with ThreadPoolExecutor when the server supports byte
    ranges, single-stream fallback otherwise.
  * Pause / resume / cancel; exact per-segment offsets are persisted to
    "<filename>.idmstate.json" every 2 seconds and removed on completion.
  * Smoothed speed, ETA, overall percentage and per-segment progress.
"""
from __future__ import annotations

import atexit
import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter

_TEMP_COOKIE_FILES: set[str] = set()


def _cleanup_temp_cookies() -> None:
    for f in list(_TEMP_COOKIE_FILES):
        try:
            if os.path.isfile(f):
                os.remove(f)
        except Exception:
            pass
    _TEMP_COOKIE_FILES.clear()


atexit.register(_cleanup_temp_cookies)


def write_mark_of_the_web(file_path: str, url: str = "", referer: str = "") -> None:
    """Attach Windows Mark-of-the-Web (Zone.Identifier ADS) to downloaded files on Windows NTFS."""
    if sys.platform != "win32" or not file_path or not os.path.isfile(file_path):
        return
    try:
        ads_path = f"{file_path}:Zone.Identifier"
        lines = ["[ZoneTransfer]", "ZoneId=3"]
        if referer and referer.lower().startswith(("http://", "https://")):
            lines.append(f"ReferrerUrl={referer}")
        if url and url.lower().startswith(("http://", "https://")):
            lines.append(f"HostUrl={url}")
        content = "\r\n".join(lines) + "\r\n"
        with open(ads_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass  # Non-NTFS drives (FAT32, exFAT) or read-only filesystems do not support streams


def protect_secret_string(plain: Optional[str]) -> str:
    """Encrypt sensitive credentials/cookies at rest using Windows DPAPI."""
    if not plain or not isinstance(plain, str):
        return ""
    if sys.platform != "win32":
        return plain
    try:
        import base64
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        raw = plain.encode("utf-8")
        b_data = ctypes.create_string_buffer(raw)
        in_blob = DATA_BLOB(len(raw), ctypes.cast(b_data, ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(in_blob), "CIDMCookie", None, None, None, 0, ctypes.byref(out_blob)):
            return plain
        res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
        return "dpapi:" + base64.b64encode(res).decode("ascii")
    except Exception:
        return plain


def unprotect_secret_string(cipher: Optional[str]) -> str:
    """Decrypt sensitive credentials/cookies at rest using Windows DPAPI."""
    if not cipher or not isinstance(cipher, str):
        return ""
    if not cipher.startswith("dpapi:"):
        return cipher
    if sys.platform != "win32":
        return ""
    try:
        import base64
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        raw = base64.b64decode(cipher[6:])
        b_data = ctypes.create_string_buffer(raw)
        in_blob = DATA_BLOB(len(raw), ctypes.cast(b_data, ctypes.POINTER(ctypes.c_char)))
        out_blob = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            return ""
        res = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
        return res.decode("utf-8", errors="replace")
    except Exception:
        return ""

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CHUNK_SIZE = 64 * 1024
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
MAX_RETRIES = 6
STATE_SAVE_INTERVAL = 2.0
SPEED_INTERVAL = 0.5
SPEED_SMOOTHING = 0.3
MIN_SEGMENT_SIZE = 128 * 1024
MIN_THREADS, MAX_THREADS = 1, 32
STATE_SUFFIX = ".idmstate.json"

_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}

# --------------------------------------------------------------------------- #
# Bundled FFmpeg & Streaming Helpers
# --------------------------------------------------------------------------- #
_CACHED_FFMPEG_PATH: Optional[str] = None


def find_ffmpeg() -> Optional[str]:
    """Find FFmpeg binary across PATH, application directories, and common install locations."""
    global _CACHED_FFMPEG_PATH
    if _CACHED_FFMPEG_PATH and os.path.isfile(_CACHED_FFMPEG_PATH):
        return _CACHED_FFMPEG_PATH

    # 1. Standard PATH lookup
    found = shutil.which("ffmpeg")
    if found and os.path.isfile(found):
        _CACHED_FFMPEG_PATH = os.path.abspath(found)
        return _CACHED_FFMPEG_PATH

    # 2. Check candidate directories
    candidate_dirs: List[Path] = []

    # PyInstaller temporary bundle
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass)
        candidate_dirs.extend([p, p / "bin", p / "vendor", p / "vendor" / "bin"])

    # Frozen executable directory
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidate_dirs.extend([
            exe_dir,
            exe_dir / "bin",
            exe_dir / "vendor",
            exe_dir / "vendor" / "bin",
        ])

    # Script directory & parents
    try:
        here = Path(__file__).resolve().parent
        candidate_dirs.extend([
            here,
            here / "bin",
            here / "vendor",
            here / "vendor" / "bin",
            here.parent / "vendor",
            here.parent / "vendor" / "bin",
            here.parent / "bin",
        ])
    except Exception:
        pass

    candidate_dirs.extend([
        Path.cwd(),
        Path.cwd() / "vendor",
        Path.cwd() / "vendor" / "bin",
        Path.cwd() / "bin",
    ])

    # Common Windows install locations
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("ProgramFiles")
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        for base in filter(None, [local_app_data, program_files, program_files_x86]):
            candidate_dirs.extend([
                Path(base) / "Programs" / "ffmpeg" / "bin",
                Path(base) / "ffmpeg" / "bin",
            ])
        candidate_dirs.extend([
            Path("C:/msys64/ucrt64/bin"),
            Path("C:/msys64/mingw64/bin"),
            Path("C:/ffmpeg/bin"),
            Path("C:/ProgramData/chocolatey/bin"),
        ])

    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    for d in candidate_dirs:
        try:
            cand = d / exe_name
            if cand.is_file():
                _CACHED_FFMPEG_PATH = str(cand.resolve())
                cand_dir = str(cand.parent.resolve())
                existing = os.environ.get("PATH", "")
                if cand_dir not in existing:
                    os.environ["PATH"] = cand_dir + os.pathsep + existing
                return _CACHED_FFMPEG_PATH
        except Exception:
            continue

    return None


_CACHED_JS_RUNTIME: Optional[Tuple[Optional[str], Optional[str]]] = None


def find_js_runtime() -> Tuple[Optional[str], Optional[str]]:
    """Detect available JavaScript runtime (node, deno, bun, quickjs) for yt-dlp challenges."""
    global _CACHED_JS_RUNTIME
    if _CACHED_JS_RUNTIME is not None:
        return _CACHED_JS_RUNTIME

    # 1. Search PATH for supported runtimes
    for name in ("node", "deno", "bun", "quickjs"):
        p = shutil.which(name)
        if p and os.path.isfile(p):
            _CACHED_JS_RUNTIME = (name, os.path.abspath(p))
            return _CACHED_JS_RUNTIME

    # 2. Check common Windows paths for node / deno / bun
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        program_files = os.environ.get("ProgramFiles")
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        candidates = [
            ("node", r"C:\Program Files\nodejs\node.exe"),
            ("node", r"C:\Program Files (x86)\nodejs\node.exe"),
        ]
        if local_app_data:
            candidates.extend([
                ("deno", os.path.join(local_app_data, "deno", "bin", "deno.exe")),
                ("bun", os.path.join(local_app_data, "bun", "bin", "bun.exe")),
            ])
        if program_files:
            candidates.append(("node", os.path.join(
                program_files, "nodejs", "node.exe")))
        if program_files_x86:
            candidates.append(("node", os.path.join(
                program_files_x86, "nodejs", "node.exe")))

        for name, p in candidates:
            if os.path.isfile(p):
                _CACHED_JS_RUNTIME = (name, os.path.abspath(p))
                return _CACHED_JS_RUNTIME

    _CACHED_JS_RUNTIME = (None, None)
    return _CACHED_JS_RUNTIME


def create_temp_cookiefile(cookies_str: Optional[str], target_url: str) -> Optional[str]:
    """Create a temporary Netscape-format cookie file from a Cookie header string.

    This avoids the yt-dlp warning:
    'Deprecated Feature: Passing cookies as a header is a potential security risk...'
    """
    if not cookies_str or not isinstance(cookies_str, str):
        return None
    cookies_str = cookies_str.strip()
    if not cookies_str:
        return None

    domain = "youtube.com"
    try:
        parsed = urllib.parse.urlparse(target_url)
        if parsed.hostname:
            domain = parsed.hostname
    except Exception:
        pass

    cookie_domain = domain if domain.startswith(".") else "." + domain

    lines = [
        "# Netscape HTTP Cookie File\n",
        "# https://curl.se/docs/http-cookies.html\n",
    ]
    valid_count = 0

    if cookies_str.startswith("# Netscape") or "\t" in cookies_str:
        lines = [cookies_str if cookies_str.endswith(
            "\n") else cookies_str + "\n"]
        valid_count = 1
    else:
        for item in cookies_str.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            name, val = item.split("=", 1)
            name = re.sub(r'[\r\n\t]+', '', name.strip())
            val = re.sub(r'[\r\n\t]+', '', val.strip())
            if name:
                lines.append(
                    f"{cookie_domain}\tTRUE\t/\tFALSE\t2147483647\t{name}\t{val}\n"
                )
                valid_count += 1

    if valid_count == 0:
        return None

    try:
        tf = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        )
        tf.writelines(lines)
        tf.close()
        _TEMP_COOKIE_FILES.add(tf.name)
        return tf.name
    except Exception:
        return None


def resolve_media_format_selector(format_id: Optional[str] = None, has_ffmpeg: bool = True) -> str:
    """Build a robust yt-dlp format selector with fallbacks that never fail on adaptive streams."""
    base_fmt = (format_id or "").strip()

    # Generic or empty request
    if not base_fmt or base_fmt in ("best", "best[ext=mp4]/best", "b"):
        if has_ffmpeg:
            return "bv*+ba/b/bestvideo+bestaudio/bestvideo/best"
        else:
            return "best[ext=mp4]/best/b/bv*+ba/bestvideo/bestaudio"

    # Audio-only request
    is_audio_only = (
        base_fmt.startswith(("ba", "bestaudio"))
        or "audio only" in base_fmt.lower()
        or (base_fmt.endswith("m4a") and "bv" not in base_fmt)
    ) and ("bv" not in base_fmt and "+" not in base_fmt)

    if is_audio_only:
        return f"{base_fmt}/ba/bestaudio/best"

    # Resolution or specific format_id request: append fallbacks so yt-dlp never crashes with
    # 'Requested format is not available'
    return f"{base_fmt}/bv*+ba/b/bestvideo+bestaudio/bestvideo/best"


# --------------------------------------------------------------------------- #
# Token Bucket Rate Limiter & Global Engine Configuration
# --------------------------------------------------------------------------- #
class TokenBucketLimiter:
    """Thread-safe global token-bucket rate limiter for bandwidth throttling."""

    def __init__(self, limit_kbps: int = 0, enabled: bool = False):
        self._lock = threading.Lock()
        self.enabled = enabled
        self.rate = max(1.0, limit_kbps * 1024.0)
        self.capacity = max(self.rate, 64.0 * 1024.0)
        self.tokens = self.capacity
        self.last_time = time.monotonic()

    def update_limit(self, limit_kbps: int, enabled: bool) -> None:
        with self._lock:
            self.enabled = enabled
            self.rate = max(1.0, limit_kbps * 1024.0)
            self.capacity = max(self.rate, 64.0 * 1024.0)
            self.tokens = min(self.tokens, self.capacity)

    def acquire(self, num_bytes: int) -> None:
        if not self.enabled or num_bytes <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_time
                self.last_time = now
                self.tokens = min(
                    self.capacity, self.tokens + elapsed * self.rate
                )

                if self.tokens >= num_bytes:
                    self.tokens -= num_bytes
                    return

                needed = num_bytes - self.tokens
                wait_time = needed / self.rate

            time.sleep(min(wait_time, 0.1))


GLOBAL_RATE_LIMITER = TokenBucketLimiter()
GLOBAL_RETRY_ATTEMPTS = 3

CATEGORY_EXTENSIONS = {
    "Videos": {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".ts", ".m3u8"},
    "Compressed": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".tgz", ".7zip"},
    "Programs": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".bat", ".cmd", ".sh"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".rtf", ".epub"},
    "Music": {".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg", ".wma", ".opus"},
}


def get_category_for_filename(filename: str) -> str:
    _, ext = os.path.splitext((filename or "").lower())
    for cat, exts in CATEGORY_EXTENSIONS.items():
        if ext in exts:
            return cat
    return "Other"


def resolve_destination_folder(base_dir: str, filename: str, auto_categorize: bool = True) -> str:
    if not auto_categorize:
        return base_dir
    cat = get_category_for_filename(filename)
    if cat != "Other":
        return os.path.join(base_dir, cat)
    return base_dir


def resolve_file_conflict(target_path: str, conflict_action: str = "Auto-rename") -> str:
    if not os.path.exists(target_path):
        return target_path
    if conflict_action and conflict_action.lower().startswith("overwrite"):
        return target_path
    dirname, filename = os.path.split(target_path)
    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        cand = os.path.join(dirname, f"{stem} ({counter}){ext}")
        if not os.path.exists(cand):
            return cand
        counter += 1


def apply_engine_settings(settings: dict) -> None:
    global DEFAULT_USER_AGENT, GLOBAL_RETRY_ATTEMPTS
    if not isinstance(settings, dict):
        return
    kbps = int(settings.get("speed_limit_kbps", 1024))
    enabled = bool(settings.get("speed_limit_enabled", False))
    GLOBAL_RATE_LIMITER.update_limit(kbps, enabled)
    GLOBAL_RETRY_ATTEMPTS = int(settings.get("retry_attempts", 3))
    custom_ua = str(settings.get("custom_user_agent", "")).strip()
    if custom_ua:
        DEFAULT_USER_AGENT = custom_ua


# --------------------------------------------------------------------------- #
# Network Interface Discovery & Source-IP Binding for Link Aggregation
# --------------------------------------------------------------------------- #
_VIRTUAL_IFACE_KEYWORDS = (
    "vethernet", "wsl", "vmware", "virtualbox", "vbox",
    "hyper-v", "docker", "loopback", "pseudo", "isatap", "teredo",
)


def get_active_interfaces() -> List[Dict[str, str]]:
    interfaces: List[Dict[str, str]] = []
    try:
        import psutil
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, addr_list in addrs.items():
            if any(k in name.lower() for k in _VIRTUAL_IFACE_KEYWORDS):
                continue
            stat = stats.get(name)
            if stat is not None and not stat.isup:
                continue
            for addr in addr_list:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                        interfaces.append({
                            "name": name,
                            "ip": ip,
                            "netmask": getattr(addr, "netmask", None) or "255.255.255.0",
                        })
    except Exception:
        pass

    # Fallback to standard library socket if psutil is unavailable or returned none
    if not interfaces:
        try:
            hostname = socket.gethostname()
            for ip_info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = ip_info[4][0]
                if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                    if not any(item["ip"] == ip for item in interfaces):
                        interfaces.append({
                            "name": f"Adapter ({ip})",
                            "ip": ip,
                            "netmask": "255.255.255.0",
                        })
        except Exception:
            pass

    return interfaces


def check_same_subnet(interfaces: List[Dict[str, Any]]) -> Optional[tuple[Dict[str, Any], Dict[str, Any], str]]:
    """Check if any two checked interfaces share the same IPv4 subnet.
    Returns (iface1, iface2, subnet_cidr) if overlap found, else None.
    """
    import ipaddress
    subnets: Dict[str, Dict[str, Any]] = {}
    for iface in interfaces:
        ip = iface.get("ip")
        if not ip:
            continue
        mask = iface.get("netmask") or "255.255.255.0"
        try:
            net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            net_str = str(net)
            if net_str in subnets:
                return subnets[net_str], iface, net_str
            subnets[net_str] = iface
        except Exception:
            pass
    return None


_INTERFACE_NAME_CACHE: Dict[str, str] = {}


def get_adapter_name_for_ip(ip: Optional[str]) -> str:
    """Return friendly adapter name for an IP, caching discovered names."""
    if not ip:
        return "Default"
    if ip in _INTERFACE_NAME_CACHE:
        return _INTERFACE_NAME_CACHE[ip]
    for iface in get_active_interfaces():
        _INTERFACE_NAME_CACHE[iface["ip"]] = iface["name"]
        if iface["ip"] == ip:
            return iface["name"]
    return ip


def _format_proxy_label(proxy_str: str) -> str:
    """Format a proxy URL for display without exposing credentials."""
    try:
        p = proxy_str.strip()
        if not re.match(r"^[a-zA-Z0-9]+://", p):
            p = "http://" + p
        parsed = urllib.parse.urlsplit(p)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        scheme = parsed.scheme.lower()
        return f"{scheme}://{host}{port}"
    except Exception:
        return proxy_str[:25]


def is_bind_or_route_error(exc: Exception) -> bool:
    """Check if an exception is caused by a source IP binding error, dead network adapter, or broken proxy."""
    err_str = str(exc).lower()
    return any(term in err_str for term in (
        "10049", "10051", "10065", "10060", "10061", "requested address is not valid",
        "unreachable host", "cannot assign requested address", "network is unreachable",
        "invalid argument", "failed to establish a new connection", "proxyerror",
        "tunnel connection failed", "connection refused", "connecttimeout", "timed out",
        "socks5", "general socks server failure", "connection closed",
    ))


class SourceAddressAdapter(HTTPAdapter):
    """Custom HTTPAdapter that binds client sockets to a specific local source IPv4 address."""

    def __init__(self, source_ip: Optional[str] = None, **kwargs):
        self.source_ip = source_ip
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        if self.source_ip:
            pool_kwargs["source_address"] = (self.source_ip, 0)
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        if self.source_ip:
            proxy_kwargs["source_address"] = (self.source_ip, 0)
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def create_bound_session(
    source_ip: Optional[str] = None,
    proxy: Optional[str] = None,
) -> requests.Session:
    """Create a requests.Session bound to the given local source IP and/or proxy."""
    session = requests.Session()
    adapter = SourceAddressAdapter(source_ip=source_ip)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if proxy:
        p = proxy.strip()
        if not re.match(r"^[a-zA-Z0-9]+://", p):
            p = "http://" + p
        session.proxies = {
            "http": p,
            "https": p,
        }
    return session


class Status:
    QUEUED = "Queued"
    PROBING = "Connecting"
    DOWNLOADING = "Downloading"
    PAUSING = "Pausing"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ERROR = "Error"
    CANCELLED = "Cancelled"
    MERGING = "Merging Audio/Video"
    EMBEDDING_SUBS = "Embedding Subtitles..."
    ACTIVE = (PROBING, DOWNLOADING, PAUSING, MERGING, EMBEDDING_SUBS)


def vtt_text_to_srt(vtt_text: str) -> str:
    """Convert WebVTT subtitle text to standard SubRip (.srt) format."""
    lines = vtt_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    srt_lines: List[str] = []
    cue_idx = 1
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            m = re.match(
                r"((?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}\.\d{3})",
                line,
            )
            if m:
                start_ts, end_ts = m.group(1), m.group(2)
                if start_ts.count(":") == 1:
                    start_ts = "00:" + start_ts
                if end_ts.count(":") == 1:
                    end_ts = "00:" + end_ts
                start_ts = start_ts.replace(".", ",")
                end_ts = end_ts.replace(".", ",")

                srt_lines.append(str(cue_idx))
                srt_lines.append(f"{start_ts} --> {end_ts}")
                cue_idx += 1
                i += 1
                cue_text: List[str] = []
                while i < len(lines) and lines[i].strip():
                    clean_text = re.sub(r"<[^>]+>", "", lines[i])
                    cue_text.append(clean_text)
                    i += 1
                srt_lines.extend(cue_text)
                srt_lines.append("")
        i += 1
    return "\n".join(srt_lines)


def convert_vtt_file_to_srt(vtt_path: str, srt_path: str) -> bool:
    """Convert a .vtt subtitle file to .srt using FFmpeg with a pure Python fallback."""
    ffmpeg_exe = find_ffmpeg()
    if ffmpeg_exe:
        try:
            res = subprocess.run(
                [ffmpeg_exe, "-y", "-i", vtt_path, srt_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            if res.returncode == 0 and os.path.exists(srt_path) and os.path.getsize(srt_path) > 0:
                return True
        except Exception:
            pass

    try:
        with open(vtt_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        srt_content = vtt_text_to_srt(content)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        return True
    except Exception:
        return False


class DownloadError(Exception):
    def __init__(self, message: str, fatal: bool = True):
        super().__init__(message)
        self.fatal = fatal


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def format_size(n: Optional[float]) -> str:
    if n is None or n < 0:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    value, i = float(n), 0
    while value >= 1024 and i < len(units) - 1:
        value /= 1024
        i += 1
    return f"{int(value)} B" if i == 0 else f"{value:.2f} {units[i]}"


def format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec <= 0:
        return "0 KB/s"
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.2f} MB/s"
    return f"{bytes_per_sec / 1024:.1f} KB/s"


def format_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


# --------------------------------------------------------------------------- #
# Filename / header helpers
# --------------------------------------------------------------------------- #
def sanitize_filename(name: str) -> str:
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip().strip(".").strip()
    if not name:
        return ""
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        name = "_" + name
    return name[:200]


def _fix_mojibake(value: str) -> str:
    """requests decodes headers as latin-1; recover UTF-8 names when possible."""
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def parse_content_disposition(value: Optional[str]) -> str:
    if not value:
        return ""
    m = re.search(
        r"filename\*\s*=\s*([^'\";]*)'[^']*'([^;]+)", value, re.IGNORECASE
    )
    if m:
        charset = m.group(1).strip() or "utf-8"
        raw = m.group(2).strip().strip('"')
        try:
            return urllib.parse.unquote(raw, encoding=charset, errors="replace")
        except LookupError:
            return urllib.parse.unquote(raw)
    m = re.search(r'filename\s*=\s*"((?:[^"\\]|\\.)*)"', value, re.IGNORECASE)
    if m:
        return _fix_mojibake(m.group(1).replace('\\"', '"'))
    m = re.search(r"filename\s*=\s*([^;]+)", value, re.IGNORECASE)
    if m:
        return _fix_mojibake(m.group(1).strip())
    return ""


def filename_from_url(url: str) -> str:
    try:
        path = urllib.parse.urlparse(url).path
    except ValueError:
        return ""
    base = os.path.basename(path.rstrip("/"))
    return sanitize_filename(urllib.parse.unquote(base))


def is_generic_name(name: Optional[str]) -> bool:
    """Return True if filename is a placeholder or generic fallback (e.g. 'download', 'file', or has no extension)."""
    if not name:
        return True
    s = str(name).strip().lower()
    stem, ext = os.path.splitext(s)
    if stem in ("download", "file", "view", "uc", "open", "index", "export", "stream", "get", "media"):
        return True
    if not ext:
        return True
    return False


def build_headers(
    cookies: Optional[str] = None,
    user_agent: Optional[str] = None,
    referer: Optional[str] = None,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    def _strip_crlf(val: Optional[str]) -> str:
        return re.sub(r'[\r\n]+', ' ', str(val or "")).strip()

    ua = _strip_crlf(user_agent) if user_agent else DEFAULT_USER_AGENT
    headers = {
        "User-Agent": ua,
        "Accept": "*/*",
        "Accept-Encoding": "identity",  # raw bytes: ranges must match file offsets
    }
    if referer:
        headers["Referer"] = _strip_crlf(referer)
    if cookies:
        headers["Cookie"] = _strip_crlf(cookies)
    if extra:
        for k, v in extra.items():
            headers[_strip_crlf(k)] = _strip_crlf(v)
    return headers


def _to_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Server probing
# --------------------------------------------------------------------------- #
@dataclass
class ProbeResult:
    file_size: int = 0
    supports_ranges: bool = False
    filename: str = ""
    final_url: str = ""


# --------------------------------------------------------------------------- #
# Cloud Storage & Direct Download URL Normalization
# --------------------------------------------------------------------------- #
def normalize_download_url(url: str) -> str:
    """Normalize file sharing and cloud storage URLs to direct download endpoints."""
    if not url or not isinstance(url, str):
        return url
    u = url.strip()

    # Google Drive view/open/uc URLs -> direct download endpoint
    m = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", u, re.IGNORECASE)
    if not m:
        m = re.search(r"drive\.google\.com/open\?.*?id=([a-zA-Z0-9_-]+)", u, re.IGNORECASE)
    if not m:
        m = re.search(r"drive\.google\.com/uc\?.*?id=([a-zA-Z0-9_-]+)", u, re.IGNORECASE)
    if not m:
        m = re.search(r"drive\.usercontent\.google\.com/download\?.*?id=([a-zA-Z0-9_-]+)", u, re.IGNORECASE)
    if m:
        file_id = m.group(1)
        return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"

    # Dropbox share link dl=0 -> dl=1
    if "dropbox.com/" in u and "dl=0" in u:
        return u.replace("dl=0", "dl=1")

    return u


def probe_url(
    url: str,
    cookies: Optional[str] = None,
    user_agent: Optional[str] = None,
    referer: Optional[str] = None,
    timeout: tuple = (CONNECT_TIMEOUT, 20),
    _depth: int = 0,
) -> ProbeResult:
    """HEAD the URL (following redirects). If HEAD fails or gives no length,
    fall back to a 1-byte ranged GET which also reveals range support."""
    url = normalize_download_url(url)
    size, ranges, disposition, final_url = 0, False, None, url
    head_ok = False
    try:
        r = requests.head(
            url,
            headers=build_headers(cookies, user_agent, referer),
            allow_redirects=True,
            timeout=timeout,
        )
        try:
            if r.status_code < 400:
                head_ok = True
                size = _to_int(r.headers.get("Content-Length"))
                ranges = r.headers.get(
                    "Accept-Ranges", ""
                ).strip().lower() == "bytes"
                disposition = r.headers.get("Content-Disposition")
                final_url = r.url or url
        finally:
            r.close()
    except requests.RequestException:
        pass

    if not head_ok or size <= 0 or not ranges:
        try:
            r = requests.get(
                url,
                headers=build_headers(
                    cookies, user_agent, referer, {"Range": "bytes=0-0"}
                ),
                stream=True,
                allow_redirects=True,
                timeout=timeout,
            )
            try:
                if r.status_code == 206:
                    m = re.match(
                        r"\s*bytes\s+\d+-\d+/(\d+)",
                        r.headers.get("Content-Range", ""),
                    )
                    if m:
                        size, ranges = int(m.group(1)), True
                    else:
                        ranges = True
                elif r.status_code == 200:
                    size = _to_int(r.headers.get("Content-Length")) or size
                    ranges = False
                elif not head_ok:
                    raise DownloadError(
                        f"HTTP {r.status_code} {r.reason or ''}".strip()
                    )
                disposition = disposition or r.headers.get(
                    "Content-Disposition"
                )
                final_url = r.url or final_url

                # Check for Google Drive virus warning HTML confirmation page
                if _depth < 3 and ("google.com" in final_url or "googleusercontent.com" in final_url):
                    c_type = (r.headers.get("Content-Type") or "").lower()
                    if "text/html" in c_type:
                        try:
                            chunk = next(r.iter_content(32768), b"").decode("utf-8", errors="ignore")
                            m_confirm = re.search(r'href="(/uc\?[^"]*confirm=[^"]*)"', chunk) or re.search(r'href="(https://drive\.usercontent\.google\.com/download\?[^"]*confirm=[^"]*)"', chunk)
                            if m_confirm:
                                conf_link = m_confirm.group(1).replace("&amp;", "&")
                                if conf_link.startswith("/"):
                                    conf_link = "https://drive.google.com" + conf_link
                                return probe_url(conf_link, cookies, user_agent, referer, timeout, _depth + 1)
                            m_token = re.search(r'name="confirm"\s+value="([^"]+)"', chunk) or re.search(r'confirm=([0-9A-Za-z_-]+)', chunk)
                            if m_token:
                                token = m_token.group(1)
                                if "confirm=" not in final_url:
                                    confirmed_url = f"{final_url}&confirm={token}"
                                else:
                                    confirmed_url = re.sub(r'confirm=[^&]*', f'confirm={token}', final_url)
                                return probe_url(confirmed_url, cookies, user_agent, referer, timeout, _depth + 1)
                        except Exception:
                            pass
            finally:
                r.close()
        except requests.RequestException as exc:
            if not head_ok:
                raise DownloadError(f"Connection failed: {exc}") from exc

    name = sanitize_filename(parse_content_disposition(disposition))
    if not name:
        name = filename_from_url(final_url) or filename_from_url(url)
    return ProbeResult(size, bool(ranges and size > 0), name, final_url)


# --------------------------------------------------------------------------- #
# Download task
# --------------------------------------------------------------------------- #
class DownloadTask:
    _ids = itertools.count(1)

    def __init__(
        self,
        url: str,
        save_dir: str,
        filename: Optional[str] = None,
        threads: int = 8,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
        subtitle_track: Optional[Dict[str, Any]] = None,
        subtitle_mode: str = "embed",
        queue_name: str = "Main Download Queue",
        queue_order: int = 0,
        selected_ips: Optional[List[str]] = None,
        proxy_pool: Optional[List[str]] = None,
        proxy_pool_enabled: bool = False,
        proxy_pool_include_direct: bool = True,
    ):
        self.id = next(self._ids)
        self.url = normalize_download_url(url)
        self.save_dir = save_dir
        self.requested_filename = sanitize_filename(filename or "") or None
        self.filename = self.requested_filename or ""
        self.threads = max(MIN_THREADS, min(MAX_THREADS, int(threads)))
        self.cookies = cookies or None
        self.user_agent = user_agent or None
        self.referer = referer or None
        self.subtitle_track = subtitle_track or None
        self.subtitle_mode = subtitle_mode or "embed"
        self.queue_name = queue_name or "Main Download Queue"
        self.queue_order = queue_order
        self.selected_ips: List[str] = [
            ip for ip in (selected_ips or []) if ip
        ]
        self.proxy_pool: List[str] = [
            p.strip() for p in (proxy_pool or []) if p.strip()
        ]
        self.proxy_pool_enabled: bool = bool(proxy_pool_enabled)
        self.proxy_pool_include_direct: bool = bool(proxy_pool_include_direct)
        self._interface_bytes: Dict[str, int] = {}
        self._interface_prev_bytes: Dict[str, int] = {}
        self._interface_speeds: Dict[str, float] = {}
        self._route_bytes: Dict[str, int] = {}
        self._route_prev_bytes: Dict[str, int] = {}
        self._route_speeds: Dict[str, float] = {}

        self.file_size = 0
        self.supports_ranges = False
        self.status = Status.QUEUED
        self.error = ""
        self.downloaded = 0
        self.speed = 0.0
        self.segments: List[Dict[str, Any]] = []

        self._lock = threading.RLock()
        self._ctl_lock = threading.RLock()
        self._pause_flag = threading.Event()
        self._cancel_flag = threading.Event()
        self._abort_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file = None
        self._probed = False
        self._file_created = False
        self._reuse_existing = False
        self._single_done = False
        self._active_responses: set = set()

    # ----- persistence of the task list (used by the UI) -------------------- #
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "save_dir": self.save_dir,
            "filename": self.filename,
            "threads": self.threads,
            "cookies": protect_secret_string(self.cookies),
            "user_agent": self.user_agent,
            "referer": self.referer,
            "file_size": self.file_size,
            "downloaded": self.downloaded,
            "subtitle_track": self.subtitle_track,
            "subtitle_mode": self.subtitle_mode,
            "queue_name": getattr(self, "queue_name", "Main Download Queue"),
            "queue_order": getattr(self, "queue_order", 0),
            "selected_ips": getattr(self, "selected_ips", []),
            "proxy_pool": getattr(self, "proxy_pool", []),
            "proxy_pool_enabled": getattr(self, "proxy_pool_enabled", False),
            "proxy_pool_include_direct": getattr(self, "proxy_pool_include_direct", True),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DownloadTask":
        task = cls(
            d["url"],
            d["save_dir"],
            d.get("filename") or None,
            d.get("threads", 8),
            unprotect_secret_string(d.get("cookies")),
            d.get("user_agent"),
            d.get("referer"),
            subtitle_track=d.get("subtitle_track"),
            subtitle_mode=d.get("subtitle_mode", "embed"),
            queue_name=d.get("queue_name", "Main Download Queue"),
            queue_order=int(d.get("queue_order", 0)),
            selected_ips=d.get("selected_ips"),
            proxy_pool=d.get("proxy_pool"),
            proxy_pool_enabled=bool(d.get("proxy_pool_enabled", False)),
            proxy_pool_include_direct=bool(
                d.get("proxy_pool_include_direct", True)
            ),
        )
        task.file_size = _to_int(d.get("file_size"))
        task.downloaded = _to_int(d.get("downloaded", 0))
        task.status = Status.PAUSED
        task._reuse_existing = True
        task._file_created = bool(task.filename)
        if task.filename and task.file_size > 0:
            if task._load_state():
                task._probed = True
        return task

    # ----- public control --------------------------------------------------- #
    @property
    def path(self) -> str:
        return os.path.join(self.save_dir, self.filename)

    @property
    def is_active(self) -> bool:
        return self.status in Status.ACTIVE

    def set_threads(self, n: int) -> None:
        """Only effective before segments have been laid out."""
        if not self.segments:
            self.threads = max(MIN_THREADS, min(MAX_THREADS, int(n)))

    def start(self) -> None:
        with self._ctl_lock:
            # If the download thread is already running/active, prevent duplicate launches
            if self._thread is not None and self._thread.is_alive():
                if self.status in (Status.DOWNLOADING, Status.PROBING):
                    return
                if self.status == Status.PAUSING:
                    # User clicked Resume while pausing: abort pause and keep running
                    self._pause_flag.clear()
                    self.status = Status.DOWNLOADING
                    return
            if self.status in (Status.QUEUED, Status.PAUSED, Status.PAUSING, Status.ERROR):
                self.error = ""
                self._pause_flag.clear()
                self._abort_flag.clear()
                self.status = Status.PROBING
                self._launch()

    resume = start

    def pause(self) -> None:
        with self._ctl_lock:
            if self.status == Status.QUEUED:
                self.status = Status.PAUSED
                return
            if self.status in (Status.PROBING, Status.DOWNLOADING):
                self._pause_flag.set()
                self.status = Status.PAUSING
                self._save_state()
                with self._lock:
                    for resp in list(getattr(self, "_active_responses", [])):
                        try:
                            resp.close()
                        except Exception:
                            pass

    def cancel(self) -> None:
        if self.status in (Status.COMPLETED, Status.CANCELLED):
            return
        self._cancel_flag.set()
        t = self._thread
        if t is not None and t.is_alive():
            self.status = Status.CANCELLED  # worker thread performs the cleanup
        else:
            self._finish_cancel()

    def delete_files(self) -> None:
        """Remove the output file and any state file (used for finished downloads)."""
        if self.filename:
            self._silent_remove(self.path)
            self._silent_remove(self._state_path())

    def refresh_url(
        self,
        new_url: str,
        new_cookies: Optional[str] = None,
        new_user_agent: Optional[str] = None,
        new_referer: Optional[str] = None,
    ) -> None:
        """Update download address (e.g. for expired CDN / temporary links) without losing progress."""
        with self._lock:
            self.url = new_url.strip()
            if new_cookies is not None:
                self.cookies = new_cookies
            if new_user_agent is not None:
                self.user_agent = new_user_agent
            if new_referer is not None:
                self.referer = new_referer
            self.error = ""
            if self.status == Status.ERROR:
                self.status = Status.PAUSED

            state_p = self._state_path()
            if os.path.exists(state_p):
                try:
                    with open(state_p, "r", encoding="utf-8") as f:
                        s_data = json.load(f)
                    s_data["url"] = self.url
                    with open(state_p, "w", encoding="utf-8") as f:
                        json.dump(s_data, f)
                except Exception:
                    pass

    def wait(self, timeout: Optional[float] = None) -> None:
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout)

    def snapshot(self) -> Dict[str, Any]:
        status = self.status
        with self._lock:
            segs = []
            for s in self.segments:
                length = (
                    s["end"] - s["start"] + 1 if s["end"] >= s["start"] else 0
                )
                done = max(0, s["pos"] - s["start"])
                if length:
                    done = min(done, length)
                source_ip = s.get("source_ip")
                proxy = s.get("proxy")
                route_label = s.get("route_label") or s.get("adapter_name")
                if not route_label:
                    if proxy:
                        route_label = f"Proxy [{_format_proxy_label(proxy)}]"
                    else:
                        route_label = get_adapter_name_for_ip(source_ip)
                segs.append({
                    "start": s["start"],
                    "end": s["end"],
                    "pos": s.get("pos", s["start"]),
                    "downloaded": done,
                    "length": length,
                    "percent": (done / length * 100.0) if length else 0.0,
                    "active": s.get("active", False),
                    "id": s.get("id", len(segs)),
                    "worker_idx": s.get("worker_idx", 0),
                    "source_ip": source_ip,
                    "proxy": proxy,
                    "route_label": route_label,
                    "adapter_name": route_label,
                })
            if segs:
                seg_dl = sum(s.get("downloaded", 0) for s in segs)
                downloaded = max(self.downloaded, seg_dl)
            else:
                downloaded = self.downloaded
            size = self.file_size
            route_stats = {}
            for lbl, b in self._route_bytes.items():
                sp = (
                    self._route_speeds.get(lbl, 0.0)
                    if status == Status.DOWNLOADING
                    else 0.0
                )
                route_stats[lbl] = {
                    "adapter": lbl,
                    "label": lbl,
                    "bytes": b,
                    "bytes_str": format_size(b),
                    "speed": sp,
                    "speed_str": format_speed(sp),
                }

        if status == Status.COMPLETED:
            percent = 100.0
        elif size > 0:
            percent = min(100.0, downloaded / size * 100.0)
        else:
            percent = 0.0
        speed = self.speed if status == Status.DOWNLOADING else 0.0
        eta = (size - downloaded) / speed if speed > 0 and size > 0 else None
        return {
            "id": self.id,
            "url": self.url,
            "filename": self.filename,
            "save_path": self.path if self.filename else "",
            "file_size": size,
            "downloaded": downloaded,
            "percent": percent,
            "speed": speed,
            "speed_str": format_speed(speed),
            "eta": eta,
            "eta_str": format_eta(eta),
            "status": status,
            "error": self.error,
            "supports_ranges": self.supports_ranges,
            "segments": segs,
            "subtitle_track": self.subtitle_track,
            "subtitle_mode": self.subtitle_mode,
            "queue_name": getattr(self, "queue_name", "Main Download Queue"),
            "queue_order": getattr(self, "queue_order", 0),
            "selected_ips": getattr(self, "selected_ips", []),
            "proxy_pool": getattr(self, "proxy_pool", []),
            "proxy_pool_enabled": getattr(self, "proxy_pool_enabled", False),
            "proxy_pool_include_direct": getattr(self, "proxy_pool_include_direct", True),
            "interface_stats": route_stats,
            "route_stats": route_stats,
        }

    # ----- internals -------------------------------------------------------- #
    def _launch(self) -> None:
        with self._ctl_lock:
            prev = self._thread
            t = threading.Thread(
                target=self._run, args=(prev,), name=f"dl-{self.id}", daemon=True
            )
            self._thread = t
            t.start()

    def _should_stop(self) -> bool:
        return (
            self._pause_flag.is_set()
            or self._cancel_flag.is_set()
            or self._abort_flag.is_set()
        )

    def _fail(self, message: str) -> None:
        with self._lock:
            if not self.error:
                self.error = message
        self._abort_flag.set()

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._should_stop():
            time.sleep(0.1)

    def _state_path(self) -> str:
        return self.path + STATE_SUFFIX

    @staticmethod
    def _silent_remove(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def _close_file(self) -> None:
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
                self._file = None

    def _finish_cancel(self) -> None:
        self._close_file()
        if self._file_created and self.filename:
            self._silent_remove(self.path)
            self._silent_remove(self._state_path())
        self.speed = 0.0
        self.status = Status.CANCELLED

    def _state_matches(self, state_path: str) -> bool:
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f).get("url") == self.url
        except (OSError, ValueError, AttributeError):
            return False

    def _choose_filename(self, detected: str) -> None:
        if self._reuse_existing and self.filename and not is_generic_name(self.filename):
            return

        # If requested_filename is generic (e.g. 'download' or missing extension)
        # but the server reported a real filename, prefer the server's detected filename!
        if is_generic_name(self.requested_filename) and detected and not is_generic_name(detected):
            name = sanitize_filename(detected)
        elif self.requested_filename and not is_generic_name(self.requested_filename):
            name = sanitize_filename(self.requested_filename)
        elif detected:
            name = sanitize_filename(detected)
        elif self.requested_filename:
            name = sanitize_filename(self.requested_filename)
        else:
            name = "download"

        if not self._reuse_existing:
            full = os.path.join(self.save_dir, name)
            if os.path.exists(full) and not self._state_matches(full + STATE_SUFFIX):
                m = re.match(r"^(.*?)(\.tar\.[A-Za-z0-9]+|\.[^.]*)$", name)
                stem, ext = (
                    (m.group(1), m.group(2)) if m and m.group(1) else (name, "")
                )
                i = 1
                while True:
                    cand = f"{stem} ({i}){ext}"
                    cand_path = os.path.join(self.save_dir, cand)
                    if not os.path.exists(cand_path) and not os.path.exists(cand_path + STATE_SUFFIX):
                        name = cand
                        break
                    i += 1
        self.filename = name
        self._reuse_existing = True

    # ----- state file ------------------------------------------------------- #
    def _save_state(self) -> None:
        if not self.supports_ranges or not self.segments or not self.filename:
            return
        with self._lock:
            if self._file is not None:
                try:
                    self._file.flush()
                except (OSError, ValueError):
                    pass
            sorted_segments = sorted(
                [dict(s) for s in self.segments], key=lambda s: int(s["start"])
            )
            data = {
                "url": self.url,
                "filename": self.filename,
                "file_size": self.file_size,
                "threads": len(self.segments),
                "segments": sorted_segments,
                "saved_at": time.time(),
            }
        tmp = self._state_path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self._state_path())
        except OSError:
            pass

    def _load_state(self) -> bool:
        try:
            with open(self._state_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("url") != self.url:
                return False
            size = int(data.get("file_size", 0))
            if size <= 0 or (self.file_size and size != self.file_size):
                return False
            if not os.path.exists(self.path):
                return False
            cur_disk_size = os.path.getsize(self.path)
            if cur_disk_size > size:
                return False
            raw_segs = data.get("segments", [])
            if not raw_segs:
                return False
            sorted_segs = sorted(raw_segs, key=lambda s: int(s["start"]))
            segs, expected_start = [], 0
            for s in sorted_segs:
                start, end, pos = int(s["start"]), int(s["end"]), int(s["pos"])
                if start != expected_start or end < start or not (start <= pos <= end + 1):
                    return False
                segs.append({
                    "start": start,
                    "end": end,
                    "pos": pos,
                    "active": False,
                    "id": len(segs),
                })
                expected_start = end + 1
            if not segs or expected_start != size:
                return False
        except (OSError, ValueError, KeyError, TypeError):
            return False
        with self._lock:
            self.segments = segs
            self.file_size = size
            self.supports_ranges = True
            self.downloaded = sum(s["pos"] - s["start"] for s in segs)
            self._probed = True
            self._reuse_existing = True
        return True

    def _init_segments(self) -> None:
        n = max(1, min(self.threads, self.file_size // MIN_SEGMENT_SIZE))
        chunk = self.file_size // n
        segs = []
        for i in range(n):
            start = i * chunk
            end = self.file_size - 1 if i == n - 1 else start + chunk - 1
            segs.append({
                "start": start,
                "end": end,
                "pos": start,
                "active": False,
                "id": i,
            })
        with self._lock:
            self.segments = segs
            self.downloaded = 0

    def _build_routes(self) -> List[Dict[str, Any]]:
        routes: List[Dict[str, Any]] = []
        direct_ips = self.selected_ips if self.selected_ips else [None]
        has_proxies = bool(self.proxy_pool_enabled and self.proxy_pool)

        if not has_proxies or self.proxy_pool_include_direct:
            for ip in direct_ips:
                label = get_adapter_name_for_ip(ip)
                if has_proxies and label == "Default":
                    label = "Direct"
                elif has_proxies:
                    label = f"{label} (Direct)"
                routes.append({
                    "source_ip": ip,
                    "proxy": None,
                    "label": label,
                })

        if has_proxies:
            for p in self.proxy_pool:
                p_clean = p.strip()
                if p_clean:
                    routes.append({
                        "source_ip": None,
                        "proxy": p_clean,
                        "label": f"Proxy [{_format_proxy_label(p_clean)}]",
                    })

        if not routes:
            routes.append(
                {"source_ip": None, "proxy": None, "label": "Default"}
            )

        return routes

    def _get_worker_route(self, worker_idx: int) -> Dict[str, Any]:
        routes = self._build_routes()
        return routes[worker_idx % len(routes)]

    def _get_worker_source_ip(self, worker_idx: int) -> Optional[str]:
        route = self._get_worker_route(worker_idx)
        return route.get("source_ip")

    def _steal_work(
        self, worker_idx: int = 0, route: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """True IDM Dynamic Work Stealing:
        When an idle worker finishes its chunk, first pick up any unassigned
        pending segment; if none, inspect all active segments, find the one
        with the largest remaining bytes (> 512 KB), split it in half,
        cap the slow worker at mid, and assign mid+1..end to this worker."""
        with self._lock:
            # 1. Pick up any existing segment that is not currently being downloaded
            for s in self.segments:
                if not s.get("active", False) and s["pos"] <= s["end"]:
                    s["active"] = True
                    s["worker_idx"] = worker_idx
                    if route:
                        s["source_ip"] = route.get("source_ip")
                        s["proxy"] = route.get("proxy")
                        label = route.get("label", "Default")
                        s["route_label"] = label
                        s["adapter_name"] = label
                    return s

            # 2. Dynamic split from slowest active worker
            best_seg = None
            max_remaining = 0
            for s in self.segments:
                if s.get("active", False):
                    rem = s["end"] - s["pos"] + 1
                    if rem > max_remaining:
                        max_remaining = rem
                        best_seg = s

            # Only steal if the chunk has more than 512 KB remaining
            if best_seg is not None and max_remaining > 512 * 1024:
                old_end = best_seg["end"]
                mid = best_seg["pos"] + max_remaining // 2
                best_seg["end"] = mid
                source_ip = route.get("source_ip") if route else None
                proxy = route.get("proxy") if route else None
                label = route.get("label", "Default") if route else "Default"
                new_seg = {
                    "start": mid + 1,
                    "end": old_end,
                    "pos": mid + 1,
                    "active": True,
                    "id": len(self.segments),
                    "worker_idx": worker_idx,
                    "source_ip": source_ip,
                    "proxy": proxy,
                    "route_label": label,
                    "adapter_name": label,
                }
                self.segments.append(new_seg)
                return new_seg
            return None

    def _process_subtitles(self) -> None:
        if not self.subtitle_track or not isinstance(self.subtitle_track, dict):
            return
        sub_url = str(self.subtitle_track.get("url") or "").strip()
        if not sub_url:
            return

        if (getattr(self, "kind", None) == "media" or self.__class__.__name__ == "MediaDownloadTask") and self.subtitle_track.get("lang"):
            if not sub_url.lower().endswith((".vtt", ".srt")):
                return

        with self._lock:
            self.status = Status.EMBEDDING_SUBS
            if hasattr(self, "merge_state"):
                self.merge_state = "Downloading and processing subtitles..."

        try:
            video_path = self.path
            if not video_path or not os.path.exists(video_path):
                stem = (
                    os.path.splitext(self.filename)[0] if self.filename else ""
                )
                if stem and os.path.isdir(self.save_dir):
                    for f in os.listdir(self.save_dir):
                        if f.startswith(stem) and f.lower().endswith(
                            (".mp4", ".mkv", ".webm", ".ts")
                        ):
                            video_path = os.path.join(self.save_dir, f)
                            break
            if not video_path or not os.path.exists(video_path):
                return

            base_stem = os.path.splitext(video_path)[0]
            ext = os.path.splitext(video_path)[1].lower()

            sub_ref = self.subtitle_track.get("referer") or self.referer
            sub_origin = self.subtitle_track.get(
                "origin"
            ) or getattr(self, "origin", None)
            sub_cookies = self.subtitle_track.get("cookies") or self.cookies
            sub_ua = (
                self.subtitle_track.get("user_agent")
                or self.user_agent
                or DEFAULT_USER_AGENT
            )

            headers = build_headers(sub_cookies, sub_ua, sub_ref)
            if sub_origin:
                headers["Origin"] = sub_origin

            resp = requests.get(sub_url, headers=headers, timeout=(10, 25))
            if resp.status_code >= 400:
                return

            sub_bytes = resp.content
            is_vtt = ".vtt" in sub_url.lower() or b"WEBVTT" in sub_bytes[:100]

            temp_sub_path = base_stem + (".vtt" if is_vtt else ".srt")
            with open(temp_sub_path, "wb") as sf:
                sf.write(sub_bytes)

            srt_path = base_stem + ".srt"
            if is_vtt:
                convert_vtt_file_to_srt(temp_sub_path, srt_path)
                if temp_sub_path != srt_path and os.path.exists(temp_sub_path):
                    try:
                        os.remove(temp_sub_path)
                    except OSError:
                        pass

            mode = (self.subtitle_mode or "embed").lower()
            ffmpeg_exe = find_ffmpeg()

            if (
                mode == "embed"
                and ffmpeg_exe
                and ext in (".mp4", ".m4v", ".mov")
                and os.path.exists(srt_path)
            ):
                with self._lock:
                    self.status = Status.EMBEDDING_SUBS
                    if hasattr(self, "merge_state"):
                        self.merge_state = "Embedding subtitles into MP4 via FFmpeg..."

                temp_muxed = base_stem + ".sub_mux.mp4"
                lang_code = self.subtitle_track.get("lang") or "eng"
                cmd = [
                    ffmpeg_exe,
                    "-y",
                    "-i",
                    video_path,
                    "-i",
                    srt_path,
                    "-c",
                    "copy",
                    "-c:s",
                    "mov_text",
                    "-metadata:s:s:0",
                    f"language={lang_code}",
                    temp_muxed,
                ]
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if (
                    proc.returncode == 0
                    and os.path.exists(temp_muxed)
                    and os.path.getsize(temp_muxed) > 0
                ):
                    os.replace(temp_muxed, video_path)
                    if os.path.exists(srt_path):
                        try:
                            os.remove(srt_path)
                        except OSError:
                            pass
                else:
                    if os.path.exists(temp_muxed):
                        try:
                            os.remove(temp_muxed)
                        except OSError:
                            pass
        except Exception:
            pass

    # ----- main thread of a task ------------------------------------------- #
    def _run(self, prev: Optional[threading.Thread]) -> None:
        if prev is not None and prev.is_alive():
            prev.join(timeout=2.0)
        self._pause_flag.clear()
        self._abort_flag.clear()
        self._single_done = False
        if self._cancel_flag.is_set():
            return
        if self._pause_flag.is_set():
            self.status = Status.PAUSED
            return
        self.error = ""
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            if self._should_stop():
                self.status = Status.PAUSED
                return
            if not self._probed:
                # If we have an existing state file and partial file on disk, load state directly
                if self.filename and self.file_size > 0 and self._load_state():
                    self._probed = True
                else:
                    if self._should_stop():
                        self.status = Status.PAUSED
                        return
                    self.status = Status.PROBING
                    old_size = self.file_size
                    res = probe_url(
                        self.url, self.cookies, self.user_agent, self.referer
                    )
                    if self._cancel_flag.is_set():
                        self._finish_cancel()
                        return
                    if self._pause_flag.is_set():
                        self.status = Status.PAUSED
                        return
                    self.file_size = res.file_size
                    self.supports_ranges = res.supports_ranges
                    if self.segments and (
                        res.file_size != old_size or not res.supports_ranges
                    ):
                        with self._lock:
                            self.segments, self.downloaded = [], 0
                    if not self.filename or not self._reuse_existing:
                        self._choose_filename(res.filename)
                    self._probed = True
            if self._pause_flag.is_set():
                self.status = Status.PAUSED
                return
            # Disk safety: verify available drive space before file allocation/writing
            if self.file_size and self.file_size > 0:
                try:
                    usage = shutil.disk_usage(self.save_dir)
                    needed = max(0, self.file_size - self.downloaded)
                    if usage.free < (needed + 50 * 1024 * 1024):
                        free_mb = usage.free / (1024 * 1024)
                        needed_mb = needed / (1024 * 1024)
                        self._fail(f"Not enough disk space (need {needed_mb:.1f} MB, {free_mb:.1f} MB free)")
                        return
                except Exception:
                    pass
            if self.supports_ranges and self.file_size > 0:
                self._run_segmented()
            else:
                self._run_single()
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self._close_file()
            if self._cancel_flag.is_set():
                self._finish_cancel()
            else:
                self.error = str(exc) or exc.__class__.__name__
                self.status = Status.ERROR
            self.speed = 0.0

    def _monitor(self, futures: list, persist: bool) -> None:
        last_save = last_tick = time.monotonic()
        last_bytes = self.downloaded
        self.speed = 0.0
        while True:
            finished = all(f.done() for f in futures)
            now = time.monotonic()
            dt = now - last_tick
            if dt >= SPEED_INTERVAL or finished:
                if dt > 0:
                    inst = (self.downloaded - last_bytes) / dt
                    self.speed = (
                        inst
                        if self.speed == 0
                        else (
                            self.speed * (1 - SPEED_SMOOTHING)
                            + inst * SPEED_SMOOTHING
                        )
                    )
                    if self.speed < 1:
                        self.speed = 0.0

                    with self._lock:
                        for lbl, cur_b in self._route_bytes.items():
                            prev_b = self._route_prev_bytes.get(lbl, 0)
                            r_inst = max(0.0, (cur_b - prev_b) / dt)
                            old_sp = self._route_speeds.get(lbl, 0.0)
                            new_sp = (
                                r_inst
                                if old_sp == 0
                                else (
                                    old_sp * (1 - SPEED_SMOOTHING)
                                    + r_inst * SPEED_SMOOTHING
                                )
                            )
                            self._route_speeds[lbl] = (
                                new_sp if new_sp >= 1.0 else 0.0
                            )
                            self._route_prev_bytes[lbl] = cur_b

                last_bytes, last_tick = self.downloaded, now
            if persist and now - last_save >= STATE_SAVE_INTERVAL:
                self._save_state()
                last_save = now
            if finished:
                break
            time.sleep(0.1)

    def _run_segmented(self) -> None:
        path = self.path
        have_state = bool(self.segments) or self._load_state()
        if have_state:
            if not os.path.exists(path):
                have_state = False
            elif os.path.getsize(path) != self.file_size:
                try:
                    with open(path, "a+b") as f:
                        f.truncate(self.file_size)
                except OSError:
                    have_state = False
        if not have_state:
            self._init_segments()
            with open(path, "wb") as f:
                f.truncate(self.file_size)
        else:
            with self._lock:
                self.downloaded = sum(
                    max(0, s.get("pos", s["start"]) - s["start"])
                    for s in self.segments
                )
        self._file_created = True
        self._file = open(path, "r+b")
        self.status = Status.DOWNLOADING
        self._save_state()

        pending = [
            i for i, s in enumerate(self.segments) if s["pos"] <= s["end"]
        ]
        worker_count = max(1, min(self.threads, len(pending))) if pending else 1
        executor = ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix=f"seg{self.id}"
        )
        futures = [
            executor.submit(self._segment_worker, seg_idx, worker_idx)
            for worker_idx, seg_idx in enumerate(pending[:worker_count])
        ]
        try:
            self._monitor(futures, persist=True)
        finally:
            executor.shutdown(wait=True)
        for f in futures:
            exc = f.exception()
            if exc is not None:
                self._fail(str(exc))

        if self._cancel_flag.is_set():
            self._finish_cancel()
            return
        with self._lock:
            complete = all(s["pos"] > s["end"] for s in self.segments)
        if complete:
            self._close_file()
            self._silent_remove(self._state_path())
            self.speed = 0.0
            self._process_subtitles()
            self.status = Status.COMPLETED
            write_mark_of_the_web(self.dest_path, self.url, self.referer)
        elif self._abort_flag.is_set():
            self._save_state()
            self._close_file()
            self.speed = 0.0
            self.status = Status.ERROR
        else:
            self._save_state()
            self._close_file()
            self.speed = 0.0
            self.status = Status.PAUSED

    def _segment_worker(self, initial_idx: int, worker_idx: int = 0) -> None:
        if initial_idx >= len(self.segments):
            return
        curr_seg = self.segments[initial_idx]
        route = self._get_worker_route(worker_idx)
        assigned_ip = route.get("source_ip")
        assigned_proxy = route.get("proxy")
        route_label = route.get("label", "Default")

        with self._lock:
            curr_seg["active"] = True
            curr_seg["worker_idx"] = worker_idx
            curr_seg["source_ip"] = assigned_ip
            curr_seg["proxy"] = assigned_proxy
            curr_seg["route_label"] = route_label
            curr_seg["adapter_name"] = route_label

        session = create_bound_session(
            source_ip=assigned_ip, proxy=assigned_proxy
        )

        try:
            while not self._should_stop():
                seg = curr_seg
                retries = 0
                while not self._should_stop():
                    with self._lock:
                        pos, end = seg["pos"], seg["end"]
                    if pos > end:
                        break
                    progressed = False
                    try:
                        resp = session.get(
                            self.url,
                            headers=build_headers(
                                self.cookies,
                                self.user_agent,
                                self.referer,
                                {"Range": f"bytes={pos}-{end}"},
                            ),
                            stream=True,
                            allow_redirects=True,
                            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                        )
                        with self._lock:
                            self._active_responses.add(resp)
                        try:
                            code = resp.status_code
                            if code == 206 or (
                                code == 200
                                and pos == 0
                                and end == self.file_size - 1
                            ):
                                pass
                            elif code in (408, 429) or code >= 500:
                                raise requests.HTTPError(f"HTTP {code}")
                            elif code == 200:
                                raise DownloadError(
                                    "Server ignored the byte-range request"
                                )
                            else:
                                raise DownloadError(
                                    f"HTTP {code} {resp.reason or ''}".strip()
                                )
                            for chunk in resp.iter_content(CHUNK_SIZE):
                                if self._should_stop():
                                    return
                                if not chunk:
                                    continue
                                GLOBAL_RATE_LIMITER.acquire(len(chunk))
                                with self._lock:
                                    remaining = seg["end"] - seg["pos"] + 1
                                    if remaining <= 0:
                                        break
                                    if len(chunk) > remaining:
                                        chunk = chunk[:remaining]
                                    self._file.seek(seg["pos"])
                                    self._file.write(chunk)
                                    seg["pos"] += len(chunk)
                                    self.downloaded += len(chunk)
                                    if route_label:
                                        self._route_bytes[route_label] = (
                                            self._route_bytes.get(
                                                route_label, 0)
                                            + len(chunk)
                                        )
                                    progressed = True
                                    if seg["pos"] > seg["end"]:
                                        break
                        finally:
                            with self._lock:
                                self._active_responses.discard(resp)
                            resp.close()
                    except DownloadError as exc:
                        self._fail(str(exc))
                        return
                    except (requests.RequestException, OSError) as exc:
                        # Graceful mid-download fallback on network interface disconnect or proxy failure
                        if is_bind_or_route_error(exc):
                            all_routes = self._build_routes()
                            candidates = [
                                r
                                for r in all_routes
                                if r.get("label") != route_label
                            ]
                            if candidates:
                                route = candidates[0]
                            else:
                                route = {
                                    "source_ip": None,
                                    "proxy": None,
                                    "label": "Direct Fallback",
                                }
                            assigned_ip = route.get("source_ip")
                            assigned_proxy = route.get("proxy")
                            route_label = route.get("label", "Default")
                            with self._lock:
                                curr_seg["source_ip"] = assigned_ip
                                curr_seg["proxy"] = assigned_proxy
                                curr_seg["route_label"] = route_label
                                curr_seg["adapter_name"] = route_label
                            try:
                                session.close()
                            except Exception:
                                pass
                            session = create_bound_session(
                                source_ip=assigned_ip, proxy=assigned_proxy
                            )
                            progressed = True
                            continue
                        elif isinstance(exc, OSError) and not is_bind_or_route_error(exc):
                            self._fail(f"Disk error: {exc}")
                            return
                        pass  # transient network problem: retry below
                    if progressed:
                        retries = 0
                    else:
                        retries += 1
                        max_r = max(1, GLOBAL_RETRY_ATTEMPTS)
                        if retries > max_r:
                            self._fail(
                                f"Connection failed after {max_r} retries"
                            )
                            return
                        self._sleep(min(0.5 * 2**retries, 8.0))

                with self._lock:
                    seg["active"] = False

                if self._should_stop():
                    return

                # Work Stealing: worker is idle, steal half from slowest active worker
                new_seg = self._steal_work(worker_idx, route)
                if new_seg is not None:
                    curr_seg = new_seg
                    continue
                else:
                    # No more segments to steal
                    break
        finally:
            with self._lock:
                curr_seg["active"] = False
            try:
                session.close()
            except Exception:
                pass

    def _run_single(self) -> None:
        path = self.path
        existing_size = os.path.getsize(path) if os.path.exists(path) else 0
        can_resume = bool(
            self._reuse_existing
            and existing_size > 0
            and (self.file_size <= 0 or existing_size < self.file_size)
        )
        if can_resume:
            self._file = open(path, "r+b")
            self._file.seek(existing_size)
            start_pos = existing_size
        else:
            self._file = open(path, "wb")
            start_pos = 0

        with self._lock:
            self.segments = [
                {
                    "start": 0,
                    "end": self.file_size - 1 if self.file_size > 0 else -1,
                    "pos": start_pos,
                }
            ]
            self.downloaded = start_pos
        self._file_created = True
        self.status = Status.DOWNLOADING
        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"single{self.id}"
        )
        futures = [executor.submit(self._single_worker)]
        try:
            self._monitor(futures, persist=False)
        finally:
            executor.shutdown(wait=True)
        exc = futures[0].exception()
        if exc is not None:
            self._fail(str(exc))

        self.speed = 0.0
        if self._cancel_flag.is_set():
            self._finish_cancel()
        elif self._single_done:
            self._close_file()
            self._process_subtitles()
            self.status = Status.COMPLETED
            write_mark_of_the_web(self.dest_path, self.url, self.referer)
        elif self._abort_flag.is_set():
            self._close_file()
            self.status = Status.ERROR
        else:
            self._close_file()
            self.status = Status.PAUSED

    def _single_worker(self) -> None:
        retries = 0
        while not self._should_stop():
            try:
                with self._lock:
                    pos = self.downloaded
                req_headers = build_headers(
                    self.cookies, self.user_agent, self.referer
                )
                if pos > 0:
                    req_headers["Range"] = f"bytes={pos}-"

                resp = requests.get(
                    self.url,
                    headers=req_headers,
                    stream=True,
                    allow_redirects=True,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
                with self._lock:
                    self._active_responses.add(resp)
                try:
                    code = resp.status_code
                    if code in (408, 429) or code >= 500:
                        raise requests.HTTPError(f"HTTP {code}")
                    if code >= 400:
                        raise DownloadError(
                            f"HTTP {code} {resp.reason or ''}".strip()
                        )
                    if pos > 0 and code == 206:
                        # Server accepted range resumption
                        self._file.seek(pos)
                        cr = resp.headers.get("Content-Range", "")
                        m = re.match(r"\s*bytes\s+\d+-\d+/(\d+)", cr)
                        if m:
                            total = int(m.group(1))
                            with self._lock:
                                self.file_size = total
                                self.segments[0]["end"] = total - 1
                                self.supports_ranges = True
                    else:
                        # Full file or server ignored range: start fresh
                        with self._lock:
                            self._file.seek(0)
                            self._file.truncate(0)
                            self.segments[0]["pos"] = 0
                            self.downloaded = 0
                        total = _to_int(resp.headers.get("Content-Length"))
                        if total > 0:
                            with self._lock:
                                self.file_size = total
                                self.segments[0]["end"] = total - 1
                        else:
                            with self._lock:
                                self.file_size = None
                                self.segments[0]["end"] = None
                    for chunk in resp.iter_content(CHUNK_SIZE):
                        if self._should_stop():
                            return
                        if not chunk:
                            continue
                        GLOBAL_RATE_LIMITER.acquire(len(chunk))
                        with self._lock:
                            self._file.write(chunk)
                            self.segments[0]["pos"] += len(chunk)
                            self.downloaded += len(chunk)
                    if self._should_stop():
                        return
                    with self._lock:
                        if self.file_size > 0 and self.downloaded < self.file_size:
                            raise requests.ConnectionError(
                                "Connection closed early"
                            )
                        self.file_size = self.downloaded
                        self.segments[0]["end"] = self.downloaded - 1
                        self._file.flush()
                    self._single_done = True
                    return
                finally:
                    with self._lock:
                        self._active_responses.discard(resp)
                    resp.close()
            except DownloadError as exc:
                self._fail(str(exc))
                return
            except requests.RequestException:
                retries += 1
                if retries > MAX_RETRIES // 2:
                    self._fail(
                        "Connection lost and could not be re-established"
                    )
                    return
                self._sleep(min(0.5 * 2**retries, 8.0))
            except OSError as exc:
                self._fail(f"Disk error: {exc}")
                return


# --------------------------------------------------------------------------- #
# HLS (.m3u8) video streams
# --------------------------------------------------------------------------- #
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _parse_attrs(text: str) -> Dict[str, str]:
    return {k: v.strip('"') for k, v in _ATTR_RE.findall(text)}


DRM_FRIENDLY_MESSAGE = (
    "This stream is DRM-protected (Widevine/PlayReady) and cannot be downloaded."
)


def is_drm_error(err: Any) -> bool:
    """Return True if an error indicates DRM encryption or protection."""
    txt = str(err or "").lower()
    keywords = (
        "drm protected",
        "drm-protected",
        "drm protection",
        "widevine",
        "playready",
        "fairplay",
        "sample-aes",
        "unsupported encryption",
        "key format not supported",
        "encryption format not supported",
        "this video is drm",
        "encrypted stream",
        "drm is not supported",
    )
    return any(k in txt for k in keywords)


def is_hls_url(url: str) -> bool:
    try:
        return urllib.parse.urlparse(url).path.lower().endswith((".m3u8", ".m3u"))
    except ValueError:
        return False


class HlsDownloadTask(DownloadTask):
    """Downloads an unencrypted or AES-128 HLS VOD stream.

    The media playlist is split into `threads` contiguous groups; each group is
    fetched by its own worker (shown as one "connection" in the UI). Segments
    are stored as <output>.parts/NNNNNN.seg, so an interrupted download resumes
    by skipping the parts that already exist. When all parts are present they
    are concatenated (and remuxed to MP4 if ffmpeg is on PATH).
    DRM-protected streams (SAMPLE-AES, Widevine, FairPlay...) are refused.
    """

    kind = "hls"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.supports_ranges = True
        self._items: List[Dict[str, Any]] = []
        self._ext = ".ts"
        self._remux = False
        self._done_count = 0
        self._keys: Dict[str, bytes] = {}

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["kind"] = "hls"
        return d

    @property
    def parts_dir(self) -> str:
        return self.path + ".parts"

    def _part_path(self, i: int) -> str:
        return os.path.join(self.parts_dir, f"{i:06d}.seg")

    def _load_state(self) -> bool:  # state lives in the parts directory instead
        return False

    def delete_files(self) -> None:
        super().delete_files()
        if self.filename:
            shutil.rmtree(self.parts_dir, ignore_errors=True)

    def _finish_cancel(self) -> None:
        super()._finish_cancel()
        if self._file_created and self.filename:
            shutil.rmtree(self.parts_dir, ignore_errors=True)
            self._silent_remove(self.path + ".merging")
            self._silent_remove(self.path + ".remux.mp4")

    def snapshot(self) -> Dict[str, Any]:
        s = super().snapshot()
        total = len(self._items)
        if total:
            done = self._done_count
            completed = s["status"] == Status.COMPLETED
            est = (
                s["downloaded"]
                if completed
                else (int(s["downloaded"] * total / done) if done else 0)
            )
            percent = 100.0 if completed else done / total * 100.0
            eta = (
                (est - s["downloaded"]) / s["speed"]
                if s["speed"] > 0 and est > 0
                else None
            )
            s.update(
                percent=percent,
                file_size=est,
                eta=eta,
                eta_str=format_eta(eta),
                unit="segments",
            )
        return s

    # ----- playlist --------------------------------------------------------- #
    def _get_text(self, url: str):
        try:
            r = requests.get(
                url,
                headers=build_headers(
                    self.cookies, self.user_agent, self.referer),
                allow_redirects=True,
                timeout=(CONNECT_TIMEOUT, 20),
            )
        except requests.RequestException as exc:
            raise DownloadError(f"Connection failed: {exc}") from exc
        if r.status_code >= 400:
            raise DownloadError(
                f"HTTP {r.status_code} while loading the playlist"
            )
        return r.text, r.url

    def _load_playlist(self) -> str:
        text, base = self._get_text(self.url)
        if not text.lstrip("\ufeff \r\n\t").startswith("#EXTM3U"):
            raise DownloadError("Not a valid HLS playlist")
        if "#EXT-X-STREAM-INF" in text:  # master playlist: take the highest bandwidth variant
            best_uri, best_bw, lines = None, -1, text.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF:"):
                    bw = _to_int(
                        _parse_attrs(line.split(":", 1)[1]).get("BANDWIDTH")
                    )
                    for nxt in lines[i + 1:]:
                        if nxt.strip() and not nxt.startswith("#"):
                            if bw > best_bw:
                                best_bw, best_uri = bw, nxt.strip()
                            break
            if not best_uri:
                raise DownloadError("Master playlist has no variants")
            text, base = self._get_text(urllib.parse.urljoin(base, best_uri))

        items, key, init, seq, ended = [], None, None, 0, False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                seq = _to_int(line.split(":", 1)[1])
            elif line.startswith("#EXT-X-KEY:"):
                a = _parse_attrs(line.split(":", 1)[1])
                method = a.get("METHOD", "NONE")
                if method == "NONE":
                    key = None
                elif (
                    method == "AES-128"
                    and a.get("KEYFORMAT", "identity") == "identity"
                    and a.get("URI")
                ):
                    key = {
                        "uri": urllib.parse.urljoin(base, a["URI"]),
                        "iv": a.get("IV"),
                    }
                else:
                    raise DownloadError(DRM_FRIENDLY_MESSAGE)
            elif line.startswith("#EXT-X-MAP:"):
                a = _parse_attrs(line.split(":", 1)[1])
                if "BYTERANGE" in a or not a.get("URI"):
                    raise DownloadError(
                        "Byte-range HLS streams are not supported"
                    )
                init = urllib.parse.urljoin(base, a["URI"])
            elif line.startswith("#EXT-X-BYTERANGE"):
                raise DownloadError("Byte-range HLS streams are not supported")
            elif line.startswith("#EXT-X-ENDLIST"):
                ended = True
            elif not line.startswith("#"):
                items.append({
                    "url": urllib.parse.urljoin(base, line),
                    "key": key,
                    "seq": seq,
                })
                seq += 1
        if not ended:
            raise DownloadError("Live streams are not supported")
        if not items:
            raise DownloadError("The playlist contains no media segments")
        if init:
            items.insert(0, {"url": init, "key": None, "seq": 0})
            self._ext = ".mp4"
        else:
            self._remux = find_ffmpeg() is not None
            self._ext = ".mp4" if self._remux else ".ts"
        self._items = items
        return os.path.splitext(filename_from_url(self.url))[0] or "video"

    def _hls_name(self, detected_stem: str) -> None:
        if self._reuse_existing and self.filename:
            return
        stem = (
            os.path.splitext(
                self.requested_filename or detected_stem or "video"
            )[0]
            or "video"
        )
        self.requested_filename = sanitize_filename(stem + self._ext)
        self._choose_filename("")

    # ----- run -------------------------------------------------------------- #
    def _run(self, prev: Optional[threading.Thread]) -> None:
        if prev is not None and prev.is_alive():
            prev.join()
        self._pause_flag.clear()
        self._abort_flag.clear()
        if self._cancel_flag.is_set():
            return
        self.error = ""
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            if not self._probed:
                self.status = Status.PROBING
                stem = self._load_playlist()
                if self._cancel_flag.is_set():
                    self._finish_cancel()
                    return
                self._hls_name(stem)
                self._probed = True
            elif not self._items:
                self._load_playlist()
            if self._pause_flag.is_set():
                self.status = Status.PAUSED
                return
            self._run_hls()
        except Exception as exc:  # noqa: BLE001
            if self._cancel_flag.is_set():
                self._finish_cancel()
            else:
                self.error = str(exc) or exc.__class__.__name__
                self.status = Status.ERROR
            self.speed = 0.0

    def _run_hls(self) -> None:
        total = len(self._items)
        os.makedirs(self.parts_dir, exist_ok=True)
        self._file_created = True
        have = [os.path.exists(self._part_path(i)) for i in range(total)]
        self._done_count = sum(have)
        self.downloaded = sum(
            os.path.getsize(self._part_path(i))
            for i in range(total)
            if have[i]
        )

        n = max(1, min(self.threads, total))
        size = -(-total // n)
        segs, start = [], 0
        while start < total:
            end = min(total - 1, start + size - 1)
            pos = next(
                (i for i in range(start, end + 1) if not have[i]), end + 1
            )
            segs.append({"start": start, "end": end, "pos": pos})
            start = end + 1
        with self._lock:
            self.segments = segs

        self.status = Status.DOWNLOADING
        pending = [i for i, s in enumerate(segs) if s["pos"] <= s["end"]]
        executor = ThreadPoolExecutor(
            max_workers=max(1, len(pending)), thread_name_prefix=f"hls{self.id}"
        )
        futures = [executor.submit(self._hls_worker, i) for i in pending]
        try:
            self._monitor(futures, persist=False)
        finally:
            executor.shutdown(wait=True)
        for f in futures:
            exc = f.exception()
            if exc is not None:
                self._fail(str(exc))

        self.speed = 0.0
        if self._cancel_flag.is_set():
            self._finish_cancel()
        elif all(os.path.exists(self._part_path(i)) for i in range(total)):
            self._merge(total)
        elif self._abort_flag.is_set():
            self.status = Status.ERROR
        else:
            self.status = Status.PAUSED

    def _hls_worker(self, wi: int) -> None:
        seg = self.segments[wi]
        route = self._get_worker_route(wi)
        assigned_ip = route.get("source_ip")
        assigned_proxy = route.get("proxy")
        route_label = route.get("label", "Default")
        with self._lock:
            seg["worker_idx"] = wi
            seg["source_ip"] = assigned_ip
            seg["proxy"] = assigned_proxy
            seg["route_label"] = route_label
            seg["adapter_name"] = route_label
        session = create_bound_session(
            source_ip=assigned_ip, proxy=assigned_proxy
        )
        try:
            idx, retries = seg["pos"], 0
            while idx <= seg["end"] and not self._should_stop():
                part = self._part_path(idx)
                if os.path.exists(part):
                    with self._lock:
                        seg["pos"] = idx + 1
                    idx += 1
                    continue
                try:
                    data = self._fetch_item(
                        idx, session=session, route_label=route_label
                    )
                    if data is None:  # stop requested
                        return
                    tmp = part + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(data)
                    os.replace(tmp, part)
                    with self._lock:
                        self.downloaded += len(data)
                        self._done_count += 1
                        seg["pos"] = idx + 1
                    idx += 1
                    retries = 0
                except DownloadError as exc:
                    self._fail(str(exc))
                    return
                except (requests.RequestException, OSError) as exc:
                    if is_bind_or_route_error(exc):
                        all_routes = self._build_routes()
                        candidates = [
                            r
                            for r in all_routes
                            if r.get("label") != route_label
                        ]
                        if candidates:
                            route = candidates[0]
                        else:
                            route = {
                                "source_ip": None,
                                "proxy": None,
                                "label": "Direct Fallback",
                            }
                        assigned_ip = route.get("source_ip")
                        assigned_proxy = route.get("proxy")
                        route_label = route.get("label", "Default")
                        with self._lock:
                            seg["source_ip"] = assigned_ip
                            seg["proxy"] = assigned_proxy
                            seg["route_label"] = route_label
                            seg["adapter_name"] = route_label
                        try:
                            session.close()
                        except Exception:
                            pass
                        session = create_bound_session(
                            source_ip=assigned_ip, proxy=assigned_proxy
                        )
                        continue
                    elif isinstance(exc, OSError) and not is_bind_or_route_error(exc):
                        self._fail(f"Disk error: {exc}")
                        return
                    retries += 1
                    max_r = max(1, GLOBAL_RETRY_ATTEMPTS)
                    if retries > max_r:
                        self._fail(
                            f"Segment {idx + 1} failed after {max_r} retries"
                        )
                        return
                    self._sleep(min(0.5 * 2**retries, 8.0))
        finally:
            with self._lock:
                seg["active"] = False
            try:
                session.close()
            except Exception:
                pass

    def _fetch_item(
        self,
        idx: int,
        session: Optional[requests.Session] = None,
        route_label: Optional[str] = None,
    ) -> Optional[bytes]:
        item = self._items[idx]
        sess = session or requests
        resp = sess.get(
            item["url"],
            headers=build_headers(self.cookies, self.user_agent, self.referer),
            stream=True,
            allow_redirects=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        try:
            code = resp.status_code
            if code in (408, 429) or code >= 500:
                raise requests.HTTPError(f"HTTP {code}")
            if code >= 400:
                raise DownloadError(f"HTTP {code} on segment {idx + 1}")
            buf = bytearray()
            for chunk in resp.iter_content(CHUNK_SIZE):
                if self._should_stop():
                    return None
                if chunk:
                    GLOBAL_RATE_LIMITER.acquire(len(chunk))
                    if route_label:
                        with self._lock:
                            self._route_bytes[route_label] = (
                                self._route_bytes.get(route_label, 0)
                                + len(chunk)
                            )
                buf += chunk
        finally:
            resp.close()
        data = bytes(buf)
        return self._decrypt(data, item) if item["key"] else data

    def _get_key(self, uri: str) -> bytes:
        with self._lock:
            cached = self._keys.get(uri)
        if cached:
            return cached
        routes = self._build_routes()
        primary_route = routes[0] if routes else {"source_ip": None, "proxy": None}
        session = create_bound_session(
            source_ip=primary_route.get("source_ip"),
            proxy=primary_route.get("proxy"),
        )
        try:
            r = session.get(
                uri,
                headers=build_headers(self.cookies, self.user_agent, self.referer),
                allow_redirects=True,
                timeout=(CONNECT_TIMEOUT, 20),
            )
            if r.status_code >= 400 or len(r.content) != 16:
                raise DownloadError("Could not fetch the stream's decryption key")
            content = r.content
        finally:
            session.close()
        with self._lock:
            self._keys[uri] = content
        return content

    def _decrypt(self, data: bytes, item: Dict[str, Any]) -> bytes:
        try:
            from cryptography.hazmat.primitives.ciphers import (
                Cipher,
                algorithms,
                modes,
            )
        except ImportError as exc:
            raise DownloadError(
                "Encrypted stream: run  pip install cryptography"
            ) from exc
        k = item["key"]
        key = self._get_key(k["uri"])
        try:
            if k.get("iv"):
                iv_hex = (
                    k["iv"][2:]
                    if k["iv"].lower().startswith("0x")
                    else k["iv"]
                )
                iv = bytes.fromhex(iv_hex.zfill(32))
            else:
                iv = item["seq"].to_bytes(16, "big")
            dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            out = dec.update(data) + dec.finalize()
        except ValueError as exc:
            raise DownloadError("Corrupt encrypted segment") from exc
        pad = out[-1] if out else 0
        return out[:-pad] if 1 <= pad <= 16 else out

    def _merge(self, total: int) -> None:
        self.status = Status.MERGING
        merging = self.path + ".merging"
        with open(merging, "wb") as out:
            for i in range(total):
                if self._cancel_flag.is_set():
                    break
                with open(self._part_path(i), "rb") as p:
                    shutil.copyfileobj(p, out, 1 << 20)
        if self._cancel_flag.is_set():
            self._finish_cancel()
            return
        if self._remux:
            remuxed, ok = self.path + ".remux.mp4", False
            ffmpeg_bin = find_ffmpeg() or "ffmpeg"
            try:
                r = subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        merging,
                        "-c",
                        "copy",
                        remuxed,
                    ],
                    capture_output=True,
                    timeout=3600,
                )
                ok = r.returncode == 0 and os.path.exists(remuxed)
            except (OSError, subprocess.SubprocessError):
                ok = False
            if ok:
                os.replace(remuxed, self.path)
                self._silent_remove(merging)
            else:  # ffmpeg failed: keep the raw transport stream, which players can still open
                self._silent_remove(remuxed)
                self.filename = os.path.splitext(self.filename)[0] + ".ts"
                os.replace(merging, self.path)
        else:
            os.replace(merging, self.path)
        shutil.rmtree(self.parts_dir, ignore_errors=True)
        self._process_subtitles()
        self.status = Status.COMPLETED
        write_mark_of_the_web(self.path, self.url, self.referer)


# --------------------------------------------------------------------------- #
# Media (YouTube & streaming) downloads via yt-dlp and FFmpeg
# --------------------------------------------------------------------------- #
_COMMON_MEDIA_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "tiktok.com",
    "soundcloud.com",
    "bilibili.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
)

_FILE_HOST_DOMAINS = (
    "drive.google.com",
    "docs.google.com",
    "drive.usercontent.google.com",
    "dropbox.com",
    "dl.dropboxusercontent.com",
    "onedrive.live.com",
    "1drv.ms",
    "sharepoint.com",
    "mega.nz",
    "mega.io",
    "mediafire.com",
    "box.com",
    "github.com",
    "raw.githubusercontent.com",
    "gitlab.com",
    "sourceforge.net",
    "archive.org",
)

_EXCLUDED_EXTRACTORS = {
    "googledrive",
    "googledrive:folder",
    "dropbox",
    "box",
    "generic",
}

_extractors_cache: Optional[list] = None


def is_media_url(url: str) -> bool:
    """Detect YouTube, HLS (.m3u8), DASH (.mpd), and other streaming URLs."""
    if not url or not isinstance(url, str):
        return False
    url_lower = url.lower().strip()
    try:
        parsed = urllib.parse.urlparse(url_lower)
        hostname = (parsed.hostname or "").lower()
        path = parsed.path.lower()
    except Exception:
        return False
    if not hostname:
        return False

    # Universal HLS / DASH stream detection
    if path.endswith((".m3u8", ".m3u", ".mpd")):
        return True
    if ".m3u8" in url_lower or ".mpd" in url_lower:
        return True

    # Cloud storage and file hosting domains are always direct file downloads, never yt-dlp media
    if any(
        hostname == d or hostname.endswith("." + d)
        for d in _FILE_HOST_DOMAINS
    ):
        return False

    # Common streaming platforms
    if any(
        hostname == d or hostname.endswith("." + d)
        for d in _COMMON_MEDIA_DOMAINS
    ):
        return True

    # Direct file extensions should not be routed to yt-dlp
    if path.endswith((
        ".zip", ".tar", ".gz", ".7z", ".rar", ".iso", ".exe", ".msi",
        ".bin", ".dmg", ".pkg", ".pdf", ".docx", ".xlsx", ".apk",
        ".mp4", ".webm", ".mkv", ".avi", ".mov",
    )):
        return False

    global _extractors_cache
    try:
        import yt_dlp
        if _extractors_cache is None:
            _extractors_cache = [
                ie
                for ie in yt_dlp.extractor.gen_extractors()
                if ie.IE_NAME.lower() not in _EXCLUDED_EXTRACTORS
            ]
        return any(ie.suitable(url) for ie in _extractors_cache)
    except Exception:
        return False


@dataclass
class QualityOption:
    label: str
    format_id: str
    ext: str
    height: int = 0


@dataclass
class MediaProbeResult:
    title: str = ""
    duration: int = 0
    thumbnail: str = ""
    sanitized_title: str = ""
    formats: List[QualityOption] = None
    default_filename: str = ""
    is_live: bool = False
    subtitles: List[Dict[str, Any]] = None


def probe_media(
    url: str,
    cookies: Optional[str] = None,
    user_agent: Optional[str] = None,
    referer: Optional[str] = None,
    origin: Optional[str] = None,
) -> MediaProbeResult:
    """Probe video metadata and available quality presets using yt-dlp without downloading."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloadError(
            "yt-dlp is not installed. Please run: pip install yt-dlp"
        ) from exc

    http_headers: Dict[str, str] = {}
    if user_agent:
        http_headers["User-Agent"] = user_agent
    if referer:
        http_headers["Referer"] = referer
    if origin:
        http_headers["Origin"] = origin

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "remote_components": ["ejs:github"],
    }
    ff_location = find_ffmpeg()
    if ff_location:
        ydl_opts["ffmpeg_location"] = ff_location
    rt_name, rt_path = find_js_runtime()
    if rt_name and rt_path:
        ydl_opts["js_runtimes"] = {rt_name: {"path": rt_path}}
    if http_headers:
        ydl_opts["http_headers"] = http_headers

    cookie_file = None
    if cookies:
        cookie_file = create_temp_cookiefile(cookies, url)
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

    info = None
    try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            err_msg = str(exc)
            if is_drm_error(err_msg):
                raise DownloadError(DRM_FRIENDLY_MESSAGE) from exc
            # If extraction failed with cookies (e.g. YouTube n-challenge / bot detection / format restriction),
            # retry cleanly without cookies
            if cookie_file and any(
                k in err_msg.lower()
                for k in ("format", "challenge", "bot", "sign in", "confirm")
            ):
                try:
                    retry_opts = dict(ydl_opts)
                    retry_opts.pop("cookiefile", None)
                    with yt_dlp.YoutubeDL(retry_opts) as retry_ydl:
                        info = retry_ydl.extract_info(url, download=False)
                except Exception:
                    pass
            if not info:
                if ".m3u8" in url.lower():
                    sanitized = (
                        sanitize_filename(filename_from_url(url)) or "stream"
                    )
                    if sanitized.lower().endswith((".m3u8", ".m3u")):
                        sanitized = os.path.splitext(sanitized)[0]
                    return MediaProbeResult(
                        title=sanitized,
                        duration=0,
                        thumbnail="",
                        sanitized_title=sanitized,
                        formats=[
                            QualityOption(
                                label="Best Video + Audio (MP4)",
                                format_id="bv*+ba/b",
                                ext="mp4",
                            )
                        ],
                        default_filename=f"{sanitized}.mp4",
                        is_live=False,
                    )
                if is_drm_error(str(exc)):
                    raise DownloadError(DRM_FRIENDLY_MESSAGE) from exc
                raise DownloadError(f"yt-dlp probe failed: {exc}") from exc
    finally:
        if cookie_file and os.path.exists(cookie_file):
            try:
                os.remove(cookie_file)
            except OSError:
                pass

    if not info:
        raise DownloadError("Could not retrieve media info")

    title = str(info.get("title") or "video")
    duration = _to_int(info.get("duration", 0))
    thumbnail = str(info.get("thumbnail") or "")
    sanitized = sanitize_filename(title) or "video"
    formats_raw = info.get("formats") or []
    is_live = bool(
        info.get("is_live") or info.get("live_status") == "is_live"
    )

    # Extract available video resolutions
    heights = sorted(
        {
            f.get("height")
            for f in formats_raw
            if isinstance(f.get("height"), int) and f.get("height") > 0
        },
        reverse=True,
    )

    options: List[QualityOption] = []
    # 1. Best Video + Audio (MP4)
    options.append(
        QualityOption(
            label="Best Video + Audio (MP4)",
            format_id="bv*+ba/b",
            ext="mp4",
            height=heights[0] if heights else 0,
        )
    )

    # 2. Standard resolution presets
    standard_heights = [2160, 1440, 1080, 720, 480, 360]
    for h in standard_heights:
        if any(avail >= h for avail in heights):
            options.append(
                QualityOption(
                    label=f"{h}p (MP4)",
                    format_id=f"bv*[height<={h}]+ba/b[height<={h}]/b",
                    ext="mp4",
                    height=h,
                )
            )

    # Master playlist custom resolution variants
    for f in formats_raw:
        h = f.get("height")
        fid = f.get("format_id")
        if h and h not in standard_heights and h > 0 and len(options) < 10:
            lbl = f"{h}p (MP4)"
            if not any(o.label == lbl for o in options):
                options.append(
                    QualityOption(
                        label=lbl,
                        format_id=(
                            str(fid)
                            if fid
                            else f"bv*[height<={h}]+ba/b[height<={h}]/b"
                        ),
                        ext="mp4",
                        height=h,
                    )
                )

    # 3. Audio Only (M4A)
    options.append(
        QualityOption(
            label="Audio Only (M4A)",
            format_id="ba[ext=m4a]/ba",
            ext="m4a",
            height=0,
        )
    )

    # 4. Extract Subtitles (Manual & Automatic)
    subtitles_list: List[Dict[str, Any]] = []
    seen_langs = set()
    raw_subs = info.get("subtitles") or {}
    for lang, sub_entries in raw_subs.items():
        if lang not in seen_langs:
            seen_langs.add(lang)
            first_entry = (
                sub_entries[0]
                if isinstance(sub_entries, list) and sub_entries
                else {}
            )
            name = first_entry.get("name") or lang
            lbl = f"{name} ({lang})" if name != lang else lang
            sub_url = first_entry.get("url") or ""
            subtitles_list.append({
                "label": lbl,
                "lang": lang,
                "url": sub_url,
                "is_auto": False,
            })
    if not subtitles_list:
        raw_auto = info.get("automatic_captions") or {}
        for lang, sub_entries in raw_auto.items():
            if lang not in seen_langs:
                seen_langs.add(lang)
                first_entry = (
                    sub_entries[0]
                    if isinstance(sub_entries, list) and sub_entries
                    else {}
                )
                name = first_entry.get("name") or lang
                lbl = (
                    f"{name} ({lang}) [auto]"
                    if name != lang
                    else f"{lang} [auto]"
                )
                sub_url = first_entry.get("url") or ""
                subtitles_list.append({
                    "label": lbl,
                    "lang": lang,
                    "url": sub_url,
                    "is_auto": True,
                })

    return MediaProbeResult(
        title=title,
        duration=duration,
        thumbnail=thumbnail,
        sanitized_title=sanitized,
        formats=options,
        default_filename=f"{sanitized}.mp4",
        is_live=is_live,
        subtitles=subtitles_list,
    )


class MediaDownloadTask(DownloadTask):
    """Downloads YouTube and streaming media URLs using yt-dlp and FFmpeg."""

    kind = "media"

    def __init__(
        self,
        url: str,
        save_dir: str,
        filename: Optional[str] = None,
        threads: int = 8,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
        origin: Optional[str] = None,
        stream_type: Optional[str] = None,
        format_id: Optional[str] = None,
        quality_label: Optional[str] = None,
        media_title: Optional[str] = None,
        subtitle_track: Optional[Dict[str, Any]] = None,
        subtitle_mode: str = "embed",
        selected_ips: Optional[List[str]] = None,
        proxy_pool: Optional[List[str]] = None,
        proxy_pool_enabled: bool = False,
        proxy_pool_include_direct: bool = True,
    ):
        if filename:
            filename = re.sub(r"(\.f[0-9a-zA-Z_-]+)+(?=\.[^.]+$|$)", "", filename)
            root, ext = os.path.splitext(filename)
            if not ext:
                default_ext = (
                    ".m4a"
                    if "Audio Only" in (quality_label or "")
                    else ".mp4"
                )
                filename = f"{root}{default_ext}"
        if media_title:
            media_title = re.sub(r"(\.f[0-9a-zA-Z_-]+)+$", "", media_title)

        super().__init__(
            url,
            save_dir,
            filename,
            threads,
            cookies,
            user_agent,
            referer,
            subtitle_track=subtitle_track,
            subtitle_mode=subtitle_mode,
            selected_ips=selected_ips,
            proxy_pool=proxy_pool,
            proxy_pool_enabled=proxy_pool_enabled,
            proxy_pool_include_direct=proxy_pool_include_direct,
        )
        self.origin = origin or None
        self.stream_type = (stream_type or "").lower() or None
        self.format_id = format_id or "bv*+ba/b"
        self.quality_label = quality_label or "Best Video + Audio (MP4)"
        self.media_title = media_title or ""
        self.duration = 0
        self.resolution = ""
        self.format_note = ""
        self.merge_state = "Ready"
        self.ffmpeg_status = "Available" if find_ffmpeg() else "Missing"
        self.eta = 0.0
        self.percent_from_hook = 0.0
        self.supports_ranges = True
        self._final_filepath = ""
        self._ffmpeg_proc: Optional[subprocess.Popen] = None

        if filename:
            stem = os.path.splitext(os.path.basename(filename))[0]
            self._media_base_stem = re.sub(r"(\.f[0-9a-zA-Z_-]+)+$", "", stem)
        elif media_title:
            self._media_base_stem = sanitize_filename(media_title)
        else:
            self._media_base_stem = ""

    def _sync_existing_media_bytes(self) -> None:
        """Scan save_dir for existing .part files belonging to this media to restore accurate progress."""
        stem = getattr(self, "_media_base_stem", None)
        if not stem and self.filename:
            raw_stem = os.path.splitext(self.filename)[0]
            stem = re.sub(r"(\.f[0-9a-zA-Z_-]+)+$", "", raw_stem)
        if not stem or not os.path.isdir(self.save_dir):
            return
        total_b = 0
        try:
            for fname in os.listdir(self.save_dir):
                if fname.startswith(stem) and fname.endswith((".part", ".ytdl", ".temp")):
                    fp = os.path.join(self.save_dir, fname)
                    if os.path.isfile(fp):
                        total_b += os.path.getsize(fp)
        except OSError:
            pass
        with self._lock:
            if total_b > self.downloaded:
                self.downloaded = total_b
                if self.file_size > 0:
                    self.percent_from_hook = min(99.9, (total_b / self.file_size) * 100.0)

    def _consolidate_chained_parts(self, base_stem: str) -> None:
        """Find any chained part files caused by previous bugs (e.g. .f400.f400.mp4.part)
        and adopt the largest one to canonical name stem.f<id>.ext.part so resumption succeeds."""
        if not os.path.isdir(self.save_dir):
            return
        try:
            for fname in os.listdir(self.save_dir):
                if not fname.endswith(".part"):
                    continue
                m = re.match(r"^(.*?)\.(f\d+)(?:\.f\d+)+(\.[^.]+\.part)$", fname)
                if m and m.group(1) == base_stem:
                    fmt = m.group(2)
                    ext = m.group(3)
                    target = f"{base_stem}.{fmt}{ext}"
                    src_path = os.path.join(self.save_dir, fname)
                    dst_path = os.path.join(self.save_dir, target)
                    src_size = os.path.getsize(src_path)
                    dst_size = os.path.getsize(dst_path) if os.path.exists(dst_path) else 0
                    if src_size > dst_size:
                        try:
                            if os.path.exists(dst_path):
                                os.remove(dst_path)
                            os.replace(src_path, dst_path)
                        except OSError:
                            pass
                    else:
                        try:
                            os.remove(src_path)
                        except OSError:
                            pass
        except OSError:
            pass

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["kind"] = "media"
        d["format_id"] = self.format_id
        d["quality_label"] = self.quality_label
        d["media_title"] = self.media_title
        d["duration"] = self.duration
        d["origin"] = self.origin
        d["stream_type"] = self.stream_type
        d["downloaded"] = self.downloaded
        d["percent"] = self.percent_from_hook
        d["media_stem"] = getattr(self, "_media_base_stem", "")
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MediaDownloadTask":
        task = cls(
            d["url"],
            d["save_dir"],
            d.get("filename") or None,
            d.get("threads", 8),
            unprotect_secret_string(d.get("cookies")),
            d.get("user_agent"),
            d.get("referer"),
            origin=d.get("origin"),
            stream_type=d.get("stream_type"),
            format_id=d.get("format_id"),
            quality_label=d.get("quality_label"),
            media_title=d.get("media_title"),
            subtitle_track=d.get("subtitle_track"),
            subtitle_mode=d.get("subtitle_mode", "embed"),
            selected_ips=d.get("selected_ips"),
            proxy_pool=d.get("proxy_pool"),
            proxy_pool_enabled=bool(d.get("proxy_pool_enabled", False)),
            proxy_pool_include_direct=bool(
                d.get("proxy_pool_include_direct", True)
            ),
        )
        task.file_size = _to_int(d.get("file_size"))
        task.duration = _to_int(d.get("duration", 0))
        task.downloaded = _to_int(d.get("downloaded", 0))
        task.percent_from_hook = float(d.get("percent", 0.0) or 0.0)
        saved_stem = d.get("media_stem")
        if saved_stem:
            task._media_base_stem = re.sub(r"(\.f[0-9a-zA-Z_-]+)+$", "", saved_stem)
        task.status = Status.PAUSED
        task._reuse_existing = True
        task._file_created = bool(task.filename)
        task._probed = bool(task.filename)
        task._sync_existing_media_bytes()
        return task

    def _load_state(self) -> bool:
        return False

    def delete_files(self) -> None:
        if self.filename:
            self._silent_remove(self.path)
        stem = getattr(self, "_media_base_stem", None) or (
            os.path.splitext(self.filename)[0] if self.filename else ""
        )
        if stem and os.path.isdir(self.save_dir):
            for fname in os.listdir(self.save_dir):
                if fname.startswith(stem) and (
                    fname.endswith((".part", ".ytdl", ".temp", ".merging"))
                    or fname == self.filename
                    or re.search(r"\.f[0-9a-zA-Z_-]+\.", fname)
                ):
                    self._silent_remove(os.path.join(self.save_dir, fname))

    def _finish_cancel(self) -> None:
        self.speed = 0.0
        self.status = Status.CANCELLED
        if self._ffmpeg_proc is not None:
            try:
                self._ffmpeg_proc.kill()
            except OSError:
                pass
            self._ffmpeg_proc = None
        self.delete_files()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            dl = self.downloaded
            size = self.file_size
            speed = self.speed
            status = self.status
            error = self.error
            eta = self.eta
            res = self.resolution
            fmt_note = self.format_note
            merge_st = self.merge_state
            q_label = self.quality_label
            pct_hook = self.percent_from_hook
            title = self.media_title
            ff_status = self.ffmpeg_status

        if status == Status.COMPLETED:
            percent = 100.0
        elif size > 0 and dl > 0:
            percent = min(100.0, dl / size * 100.0)
        elif pct_hook > 0:
            percent = min(100.0, pct_hook)
        elif size > 0 and dl == 0:
            percent = 0.0
        else:
            percent = 0.0

        speed_val = speed if status == Status.DOWNLOADING else 0.0
        eta_val = (
            eta
            if status == Status.DOWNLOADING and eta and eta > 0
            else (
                (size - dl) / speed_val
                if speed_val > 0 and size > dl
                else None
            )
        )

        return {
            "id": self.id,
            "url": self.url,
            "filename": self.filename,
            "save_path": self.path if self.filename else "",
            "file_size": size,
            "downloaded": dl,
            "percent": percent,
            "speed": speed_val,
            "speed_str": format_speed(speed_val),
            "eta": eta_val,
            "eta_str": format_eta(eta_val),
            "status": status,
            "error": error,
            "supports_ranges": True,
            "segments": [],
            "is_media": True,
            "kind": "media",
            "quality_label": q_label,
            "resolution": res,
            "format_note": fmt_note,
            "merge_state": merge_st,
            "ffmpeg_status": ff_status,
            "title": title,
        }

    def _progress_hook(self, d: Dict[str, Any]) -> None:
        if self._cancel_flag.is_set():
            import yt_dlp
            raise yt_dlp.utils.DownloadError("Cancelled")
        if self._pause_flag.is_set():
            import yt_dlp
            raise yt_dlp.utils.DownloadError("Paused")

        status = d.get("status")
        if status == "downloading":
            with self._lock:
                self.status = Status.DOWNLOADING
                dl = d.get("downloaded_bytes")
                if dl is not None:
                    self.downloaded = int(dl)
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    self.file_size = int(total)
                sp = d.get("speed")
                if sp is not None:
                    self.speed = float(sp)
                eta = d.get("eta")
                if eta is not None:
                    self.eta = float(eta)
                pct = d.get("_percent")
                if pct is not None:
                    self.percent_from_hook = float(pct)
                fn = d.get("filename")
                if fn:
                    self._final_filepath = fn
                    base_fn = os.path.basename(fn)
                    # Never overwrite filename with intermediate stream chunk (e.g. .f400.mp4)
                    if not re.search(r"\.f[0-9a-zA-Z_-]+\.", base_fn):
                        self.filename = base_fn
                info = d.get("info_dict") or {}
                res = info.get("resolution") or (
                    f"{info.get('width')}x{info.get('height')}"
                    if info.get("width") and info.get("height")
                    else ""
                )
                if res:
                    self.resolution = res
                fmt = info.get("format_note") or info.get("format")
                if fmt:
                    self.format_note = str(fmt)
        elif status == "finished":
            with self._lock:
                fn = d.get("filename")
                if fn:
                    self._final_filepath = fn
                    base_fn = os.path.basename(fn)
                    if not re.search(r"\.f[0-9a-zA-Z_-]+\.", base_fn):
                        self.filename = base_fn

    def _postprocessor_hook(self, d: Dict[str, Any]) -> None:
        if self._cancel_flag.is_set():
            import yt_dlp
            raise yt_dlp.utils.DownloadError("Cancelled")
        if self._pause_flag.is_set():
            import yt_dlp
            raise yt_dlp.utils.DownloadError("Paused")

        status = d.get("status")
        pp = str(d.get("postprocessor") or "")
        if status == "started":
            with self._lock:
                self.status = Status.MERGING
                self.merge_state = (
                    f"Merging with {pp}..."
                    if pp
                    else "Merging Audio and Video..."
                )
        elif status == "processing":
            with self._lock:
                self.status = Status.MERGING
                self.merge_state = "Merging in progress..."
        elif status == "finished":
            with self._lock:
                self.merge_state = (
                    f"Finished ({pp})" if pp else "Merge completed"
                )
                info = d.get("info_dict") or {}
                fn = info.get("filepath") or info.get("_filename")
                if fn and os.path.exists(fn):
                    self._final_filepath = fn
                    self.filename = os.path.basename(fn)

    def _run(self, prev: Optional[threading.Thread]) -> None:
        if prev is not None and prev.is_alive():
            prev.join(timeout=2.0)
        self._pause_flag.clear()
        self._abort_flag.clear()
        if self._cancel_flag.is_set():
            return
        if self._pause_flag.is_set():
            self.status = Status.PAUSED
            return
        self.error = ""
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            if self._should_stop():
                self.status = Status.PAUSED
                return
            if not self._probed:
                if self._should_stop():
                    self.status = Status.PAUSED
                    return
                self.status = Status.PROBING
                try:
                    probe = probe_media(
                        self.url,
                        self.cookies,
                        self.user_agent,
                        self.referer,
                        self.origin,
                    )
                    if self._cancel_flag.is_set():
                        self._finish_cancel()
                        return
                    if self._pause_flag.is_set():
                        self.status = Status.PAUSED
                        return
                    if probe.is_live:
                        raise DownloadError(
                            "Active livestream detected. Only VOD (non-live) streams are supported."
                        )
                    self.media_title = probe.title
                    self.duration = probe.duration
                    if not getattr(self, "_media_base_stem", None):
                        self._media_base_stem = probe.sanitized_title or sanitize_filename(probe.title) or "media"
                    if not self.filename:
                        ext = (
                            "m4a"
                            if "Audio Only" in (self.quality_label or "")
                            else "mp4"
                        )
                        self.filename = (
                            f"{self._media_base_stem}.{ext}"
                        )
                except Exception as probe_err:
                    if "live" in str(probe_err).lower():
                        raise
                    if not self.filename:
                        self.filename = "media.mp4"
                    if not getattr(self, "_media_base_stem", None):
                        self._media_base_stem = os.path.splitext(self.filename)[0]

                # Ensure filename has a valid extension
                if self.filename:
                    root, ext = os.path.splitext(self.filename)
                    if not ext:
                        default_ext = (
                            ".m4a"
                            if "Audio Only" in (self.quality_label or "")
                            else ".mp4"
                        )
                        self.filename = f"{root}{default_ext}"

                self._choose_filename(self.filename)
                self._probed = True

            if self._pause_flag.is_set():
                self.status = Status.PAUSED
                return

            self._run_media()
        except Exception as exc:
            if self._cancel_flag.is_set():
                self._finish_cancel()
            elif is_drm_error(str(exc)):
                self.error = DRM_FRIENDLY_MESSAGE
                self.status = Status.ERROR
                self.speed = 0.0
            else:
                self.error = str(exc) or exc.__class__.__name__
                self.status = Status.ERROR
            self.speed = 0.0

    def _run_ffmpeg_stream(self, output_path: str) -> None:
        """Fallback direct FFmpeg stream downloader with progress and speed parsing."""
        ffmpeg_exe = find_ffmpeg()
        if not ffmpeg_exe:
            raise DownloadError(
                "FFmpeg is required to download this stream, but was not found on PATH."
            )

        def _clean_hdr(v: str) -> str:
            return re.sub(r'[\r\n]+', ' ', str(v or "")).strip()

        headers_str = ""
        if self.referer:
            headers_str += f"Referer: {_clean_hdr(self.referer)}\r\n"
        if self.origin:
            headers_str += f"Origin: {_clean_hdr(self.origin)}\r\n"
        if self.user_agent:
            headers_str += f"User-Agent: {_clean_hdr(self.user_agent)}\r\n"
        if self.cookies:
            headers_str += f"Cookie: {_clean_hdr(self.cookies)}\r\n"

        cmd = [
            ffmpeg_exe,
            "-y",
            "-protocol_whitelist",
            "file,http,https,tcp,tls,crypto",
        ]
        if headers_str:
            cmd.extend(["-headers", headers_str])
        cmd.extend([
            "-i",
            self.url,
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            output_path,
        ])

        self.status = Status.DOWNLOADING
        self.merge_state = "Downloading stream via FFmpeg"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
        )
        self._ffmpeg_proc = proc

        last_time = time.monotonic()
        last_bytes = 0
        err_tail: List[str] = []

        try:
            for raw_line in proc.stderr:
                line = raw_line.strip()
                if line:
                    err_tail.append(line)
                    if len(err_tail) > 25:
                        err_tail.pop(0)
                if self._cancel_flag.is_set() or self._pause_flag.is_set():
                    proc.terminate()
                    break

                m_time = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line)
                now = time.monotonic()
                dt = now - last_time

                m_size = re.search(
                    r"size=\s*(\d+)\s*([kKMmGg]?[bB])?", line
                )
                if m_size:
                    val = int(m_size.group(1))
                    unit = (m_size.group(2) or "kB").lower()
                    if "m" in unit:
                        b = val * 1024 * 1024
                    elif "k" in unit:
                        b = val * 1024
                    else:
                        b = val
                    with self._lock:
                        self.downloaded = b
                        if dt >= 0.5:
                            inst_speed = (
                                (b - last_bytes) / dt if dt > 0 else 0.0
                            )
                            self.speed = (
                                inst_speed
                                if self.speed == 0
                                else (self.speed * 0.7 + inst_speed * 0.3)
                            )
                            last_bytes = b
                            last_time = now

                if m_time and self.duration > 0:
                    h, m, s = m_time.groups()
                    cur_sec = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(99.0, (cur_sec / self.duration) * 100.0)
                    rem_sec = max(0.0, self.duration - cur_sec)
                    with self._lock:
                        self.percent_from_hook = pct
                        self.eta = rem_sec

            proc.wait()
        finally:
            self._ffmpeg_proc = None

        if self._cancel_flag.is_set():
            self._finish_cancel()
            return
        if self._pause_flag.is_set():
            self.status = Status.PAUSED
            self.speed = 0.0
            return

        if proc.returncode != 0:
            tail_msg = " ".join(err_tail)
            if is_drm_error(tail_msg) or any(
                k in tail_msg.lower() for k in ("crypto", "key file", "sample-aes", "drm")
            ):
                raise DownloadError(DRM_FRIENDLY_MESSAGE)
            raise DownloadError(f"FFmpeg exited with code {proc.returncode}")

        if os.path.exists(output_path):
            self._process_subtitles()
            with self._lock:
                self.status = Status.COMPLETED
                self.speed = 0.0
                self.eta = 0.0
                self.percent_from_hook = 100.0
                self.merge_state = "Completed"
            if self.filename:
                write_mark_of_the_web(os.path.join(self.save_dir, self.filename), self.url, self.referer)
                self.filename = os.path.basename(output_path)
                self.file_size = os.path.getsize(output_path)
                self.downloaded = self.file_size
            write_mark_of_the_web(output_path, self.url, self.referer)

    def _run_media(self) -> None:
        try:
            import yt_dlp
        except ImportError as exc:
            raise DownloadError(
                "yt-dlp is not installed. Please run: pip install yt-dlp"
            ) from exc

        ff_location = find_ffmpeg()
        has_ffmpeg = ff_location is not None
        if not has_ffmpeg:
            self.ffmpeg_status = "FFmpeg missing (fallback: single stream)"
            self.merge_state = "FFmpeg not found; single stream download"
        else:
            self.ffmpeg_status = "FFmpeg available"
            self.merge_state = "Ready / FFmpeg active"

        format_selector = resolve_media_format_selector(
            self.format_id, has_ffmpeg=has_ffmpeg
        )

        base_stem = getattr(self, "_media_base_stem", None)
        if not base_stem:
            raw = self.filename or self.media_title or "media"
            base_stem = os.path.splitext(os.path.basename(raw))[0]
            base_stem = re.sub(r"(\.f[0-9a-zA-Z_-]+)+$", "", base_stem)
            self._media_base_stem = base_stem
        else:
            base_stem = re.sub(r"(\.f[0-9a-zA-Z_-]+)+$", "", base_stem)
            self._media_base_stem = base_stem

        self._consolidate_chained_parts(base_stem)
        stem = base_stem
        outtmpl = os.path.join(self.save_dir, f"{stem}.%(ext)s")

        threads = min(16, max(1, self.threads))
        ydl_opts: Dict[str, Any] = {
            "format": format_selector,
            "outtmpl": outtmpl,
            "concurrent_fragment_downloads": threads,
            "continuedl": True,
            "noprogress": True,
            "updatetime": False,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
        }
        if self.subtitle_track and isinstance(self.subtitle_track, dict):
            lang_code = self.subtitle_track.get("lang") or ""
            if lang_code:
                ydl_opts["writesubtitles"] = True
                ydl_opts["writeautomaticsub"] = True
                ydl_opts["subtitleslangs"] = [lang_code]
                ydl_opts["subtitlesformat"] = "srt"
                if (
                    (self.subtitle_mode or "embed").lower() == "embed"
                    and has_ffmpeg
                ):
                    pp_list = ydl_opts.setdefault("postprocessors", [])
                    pp_list.append({"key": "FFmpegEmbedSubtitle"})
        if ff_location:
            ydl_opts["ffmpeg_location"] = ff_location
        if has_ffmpeg:
            ydl_opts["merge_output_format"] = "mp4"
        if GLOBAL_RATE_LIMITER.enabled and GLOBAL_RATE_LIMITER.rate > 0:
            ydl_opts["ratelimit"] = int(GLOBAL_RATE_LIMITER.rate)

        if self.selected_ips:
            ydl_opts["source_address"] = self.selected_ips[0]
        if self.proxy_pool_enabled and self.proxy_pool:
            ydl_opts["proxy"] = self.proxy_pool[0]

        rt_name, rt_path = find_js_runtime()
        if rt_name and rt_path:
            ydl_opts["js_runtimes"] = {rt_name: {"path": rt_path}}
            ydl_opts["remote_components"] = ["ejs:github"]

        http_headers: Dict[str, str] = {}
        if self.user_agent:
            http_headers["User-Agent"] = self.user_agent
        if self.referer:
            http_headers["Referer"] = self.referer
        if self.origin:
            http_headers["Origin"] = self.origin
        if http_headers:
            ydl_opts["http_headers"] = http_headers

        cookie_file = None
        if self.cookies:
            cookie_file = create_temp_cookiefile(self.cookies, self.url)
            if cookie_file:
                ydl_opts["cookiefile"] = cookie_file

        self.status = Status.DOWNLOADING
        self._file_created = True

        def _execute_ydl(opts: Dict[str, Any]) -> None:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self.url])

        try:
            current_opts = dict(ydl_opts)
            try:
                _execute_ydl(current_opts)
            except yt_dlp.utils.DownloadError as dl_err:
                # 1. Retry without bound source_address if route/adapter is unreachable
                if "source_address" in current_opts and is_bind_or_route_error(dl_err):
                    current_opts.pop("source_address", None)
                    try:
                        _execute_ydl(current_opts)
                    except yt_dlp.utils.DownloadError as dl_err2:
                        dl_err = dl_err2
                    else:
                        dl_err = None

                # 2. Retry without cookiefile if YouTube challenge/bot/format restriction occurs
                if dl_err is not None:
                    msg = str(dl_err)
                    if "cookiefile" in current_opts and any(
                        k in msg.lower()
                        for k in ("format", "challenge", "bot", "sign in", "confirm")
                    ):
                        current_opts.pop("cookiefile", None)
                        _execute_ydl(current_opts)
                    else:
                        raise dl_err

            if self._cancel_flag.is_set():
                self._finish_cancel()
                return
            if self._pause_flag.is_set():
                self.status = Status.PAUSED
                self.speed = 0.0
                return

            if self._final_filepath and os.path.exists(self._final_filepath):
                self.filename = os.path.basename(self._final_filepath)
                self.file_size = os.path.getsize(self._final_filepath)
                self.downloaded = self.file_size
            elif os.path.isdir(self.save_dir):
                for cand in os.listdir(self.save_dir):
                    if cand.startswith(stem) and not cand.endswith(
                        (".part", ".ytdl", ".temp", ".merging")
                    ):
                        full = os.path.join(self.save_dir, cand)
                        if os.path.isfile(full):
                            self.filename = cand
                            self.file_size = os.path.getsize(full)
                            self.downloaded = self.file_size
                            break

            self._process_subtitles()

            with self._lock:
                self.status = Status.COMPLETED
                self.speed = 0.0
                self.eta = 0.0
                self.percent_from_hook = 100.0
                self.merge_state = "Completed"
            if self.filename:
                write_mark_of_the_web(os.path.join(self.save_dir, self.filename), self.url, self.referer)

        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc)
            if self._cancel_flag.is_set() or "Cancelled" in msg:
                self._finish_cancel()
                return
            elif self._pause_flag.is_set() or "Paused" in msg:
                self.status = Status.PAUSED
                self.speed = 0.0
                return

            if is_drm_error(msg):
                self.error = DRM_FRIENDLY_MESSAGE
                self.status = Status.ERROR
                self.speed = 0.0
                return

            # Fall back to FFmpeg directly for .m3u8 streams
            is_hls = (
                ".m3u8" in self.url.lower() or self.stream_type == "hls"
            )
            if is_hls and find_ffmpeg() and not self._cancel_flag.is_set():
                try:
                    self._run_ffmpeg_stream(
                        os.path.join(self.save_dir, f"{stem}.mp4")
                    )
                    return
                except Exception as ff_exc:
                    self.error = (
                        f"yt-dlp error: {msg} | FFmpeg error: {ff_exc}"
                    )
                    self.status = Status.ERROR
                    self.speed = 0.0
                    return

            self.error = msg
            self.status = Status.ERROR
            self.speed = 0.0
        except Exception as exc:
            if self._cancel_flag.is_set():
                self._finish_cancel()
            elif is_drm_error(str(exc)):
                self.error = DRM_FRIENDLY_MESSAGE
                self.status = Status.ERROR
                self.speed = 0.0
            else:
                is_hls = (
                    ".m3u8" in self.url.lower() or self.stream_type == "hls"
                )
                if is_hls and find_ffmpeg():
                    try:
                        self._run_ffmpeg_stream(
                            os.path.join(self.save_dir, f"{stem}.mp4")
                        )
                        return
                    except Exception as ff_exc:
                        self.error = (
                            f"Stream error: {exc} | FFmpeg: {ff_exc}"
                        )
                else:
                    self.error = str(exc) or exc.__class__.__name__
                self.status = Status.ERROR
            self.speed = 0.0
        finally:
            if cookie_file and os.path.exists(cookie_file):
                try:
                    os.remove(cookie_file)
                except OSError:
                    pass


# --------------------------------------------------------------------------- #
# Checksum Verifier & System Actions
# --------------------------------------------------------------------------- #
def calculate_file_checksum(
    filepath: str,
    algo: str = "sha256",
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Calculate MD5, SHA-1, or SHA-256 hash of a file with progress updates."""
    import hashlib
    algo_clean = (algo or "sha256").lower()
    if algo_clean == "md5":
        hasher = hashlib.md5()
    elif algo_clean == "sha1":
        hasher = hashlib.sha1()
    else:
        hasher = hashlib.sha256()

    if not os.path.isfile(filepath):
        return ""

    total_size = os.path.getsize(filepath)
    processed = 0

    with open(filepath, "rb") as f:
        while True:
            if cancel_event and cancel_event.is_set():
                return ""
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            processed += len(chunk)
            if progress_callback:
                progress_callback(processed, total_size)

    return hasher.hexdigest().lower()


def execute_system_action(action: str) -> None:
    """Perform post-queue computer action (Shut down, Sleep, Exit)."""
    act = (action or "").lower().strip()
    if "shut" in act:
        if sys.platform == "win32":
            subprocess.run(["shutdown", "/s", "/t", "10"], check=False)
        elif sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e", 'tell app "System Events" to shut down'],
                check=False,
            )
        else:
            subprocess.run(["shutdown", "-h", "now"], check=False)
    elif "sleep" in act or "suspend" in act:
        if sys.platform == "win32":
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                check=False,
            )
        elif sys.platform == "darwin":
            subprocess.run(["pmset", "sleepnow"], check=False)
        else:
            subprocess.run(["systemctl", "suspend"], check=False)


# --------------------------------------------------------------------------- #
# Factories
# --------------------------------------------------------------------------- #
def create_task(
    url: str,
    save_dir: str,
    filename: Optional[str] = None,
    threads: int = 8,
    cookies: Optional[str] = None,
    user_agent: Optional[str] = None,
    referer: Optional[str] = None,
    origin: Optional[str] = None,
    kind: Optional[str] = None,
    stream_type: Optional[str] = None,
    format_id: Optional[str] = None,
    quality_label: Optional[str] = None,
    media_title: Optional[str] = None,
    auto_categorize: bool = False,
    conflict_action: str = "Auto-rename",
    subtitle_track: Optional[Dict[str, Any]] = None,
    subtitle_mode: str = "embed",
    queue_name: str = "Main Download Queue",
    queue_order: int = 0,
    selected_ips: Optional[List[str]] = None,
    proxy_pool: Optional[List[str]] = None,
    proxy_pool_enabled: bool = False,
    proxy_pool_include_direct: bool = True,
) -> DownloadTask:
    url = normalize_download_url(url)
    if filename:
        if auto_categorize:
            save_dir = resolve_destination_folder(
                save_dir, filename, auto_categorize=True
            )
        if conflict_action:
            full_path = resolve_file_conflict(
                os.path.join(save_dir, filename), conflict_action
            )
            save_dir, filename = os.path.split(full_path)

    # Route pure HLS streams to specialized HlsDownloadTask unless yt-dlp media extraction is requested
    if kind == "hls" or (is_hls_url(url) and not format_id and kind != "media"):
        task = HlsDownloadTask(
            url,
            save_dir,
            filename,
            threads,
            cookies,
            user_agent,
            referer,
            subtitle_track=subtitle_track,
            subtitle_mode=subtitle_mode,
            selected_ips=selected_ips,
            proxy_pool=proxy_pool,
            proxy_pool_enabled=proxy_pool_enabled,
            proxy_pool_include_direct=proxy_pool_include_direct,
        )
    elif (
        kind in ("media", "dash")
        or (stream_type and stream_type.lower() in ("hls", "dash", "media"))
        or is_media_url(url)
    ):
        task = MediaDownloadTask(
            url,
            save_dir,
            filename,
            threads,
            cookies,
            user_agent,
            referer,
            origin=origin,
            stream_type=stream_type,
            format_id=format_id,
            quality_label=quality_label,
            media_title=media_title,
            subtitle_track=subtitle_track,
            subtitle_mode=subtitle_mode,
            selected_ips=selected_ips,
            proxy_pool=proxy_pool,
            proxy_pool_enabled=proxy_pool_enabled,
            proxy_pool_include_direct=proxy_pool_include_direct,
        )
    else:
        task = DownloadTask(
            url,
            save_dir,
            filename,
            threads,
            cookies,
            user_agent,
            referer,
            subtitle_track=subtitle_track,
            subtitle_mode=subtitle_mode,
            selected_ips=selected_ips,
            proxy_pool=proxy_pool,
            proxy_pool_enabled=proxy_pool_enabled,
            proxy_pool_include_direct=proxy_pool_include_direct,
        )
    task.queue_name = queue_name or "Main Download Queue"
    task.queue_order = queue_order
    return task


def task_from_dict(d: Dict[str, Any]) -> DownloadTask:
    kind = str(d.get("kind") or "").lower()
    st = str(d.get("stream_type") or "").lower()
    url = d.get("url", "")
    if kind == "hls" or (is_hls_url(url) and not is_media_url(url)):
        task = HlsDownloadTask.from_dict(d)
    elif (
        kind in ("media", "dash")
        or st in ("hls", "dash", "media")
        or is_media_url(url)
    ):
        task = MediaDownloadTask.from_dict(d)
    else:
        task = DownloadTask.from_dict(d)
    task.queue_name = d.get("queue_name", "Main Download Queue")
    task.queue_order = int(d.get("queue_order", 0))
    return task
