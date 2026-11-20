"""main.py - Starts the local HTTP bridge and the PySide6 GUI."""
from __future__ import annotations
from ui import MainWindow, create_app_icon, load_settings
from server import HOST, PORT, DEFAULT_PORTS, BridgeServer, BridgeSignals
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

import json
import logging
import os
import signal
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path


# --------------------------------------------------------------------------- #
# Bundled FFmpeg PATH Resolution: ensure bundled binaries are found on PATH
# --------------------------------------------------------------------------- #
def _setup_bundled_paths() -> None:
    search_dirs: list[Path] = []

    # 1. PyInstaller onefile temporary extraction directory
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass)
        search_dirs.extend([p, p / "bin", p / "vendor", p / "vendor" / "bin"])

    # 2. PyInstaller onedir executable directory (and subfolders)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        search_dirs.extend([
            exe_dir,
            exe_dir / "bin",
            exe_dir / "vendor",
            exe_dir / "vendor" / "bin",
        ])

    # 3. Standard Python execution source directory
    src_dir = Path(__file__).resolve().parent
    search_dirs.extend([
        src_dir,
        src_dir / "bin",
        src_dir / "vendor",
        src_dir / "vendor" / "bin",
        src_dir.parent / "vendor",
        src_dir.parent / "vendor" / "bin",
        src_dir.parent / "bin",
    ])

    existing_path = os.environ.get("PATH", "")
    # Compare whole path entries (a substring test wrongly treats "C:\\foo" as
    # already present when PATH contains "C:\\foobar").
    present = {os.path.normcase(os.path.normpath(p))
               for p in existing_path.split(os.pathsep) if p}
    to_prepend: list[str] = []
    for d in search_dirs:
        try:
            if d.is_dir():
                s = str(d)
                key = os.path.normcase(os.path.normpath(s))
                if key not in present:
                    present.add(key)
                    to_prepend.append(s)
        except Exception:
            pass

    if to_prepend:
        os.environ["PATH"] = os.pathsep.join(
            to_prepend) + os.pathsep + existing_path


_setup_bundled_paths()


# --------------------------------------------------------------------------- #
# Crash logging: unhandled exceptions go to ~/.cidm/cidm.log instead of vanishing
# (a windowed/tray app has no console to show tracebacks).
# --------------------------------------------------------------------------- #
def _setup_logging() -> None:
    try:
        log_dir = Path.home() / ".cidm"
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(log_dir / "cidm.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    except Exception:
        return

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.error("Unhandled exception:\n%s",
                      "".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


_setup_logging()

# Set explicit Application User Model ID (AUMID) so Windows Taskbar groups and window
# buttons display CIDM's custom app icon rather than generic python.exe / pythonw.exe
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "cidm.downloadmanager.desktop.1.0"
        )
    except Exception:
        pass


def get_running_bridge_info() -> tuple[int | None, str]:
    """Return (port, token) for the currently running CIDM bridge instance."""
    # Fast path: check cached runtime bridge_port.json first
    try:
        appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        p_file = Path(appdata) / "CIDM" / "bridge_port.json"
        if p_file.is_file():
            data = json.loads(p_file.read_text(encoding="utf-8"))
            p = data.get("port")
            token = str(data.get("token") or "")
            if isinstance(p, int):
                req = urllib.request.Request(f"http://{HOST}:{p}/ping", method="GET")
                with urllib.request.urlopen(req, timeout=0.6) as resp:
                    if resp.status == 200:
                        info = json.loads(resp.read(4096).decode("utf-8", "replace"))
                        if isinstance(info, dict) and info.get("app") == "CIDM":
                            return p, token
    except Exception:
        pass

    # Probe all default/fallback candidate ports
    for p in DEFAULT_PORTS:
        try:
            req = urllib.request.Request(f"http://{HOST}:{p}/ping", method="GET")
            with urllib.request.urlopen(req, timeout=0.35) as resp:
                if resp.status == 200:
                    info = json.loads(resp.read(4096).decode("utf-8", "replace"))
                    if isinstance(info, dict) and info.get("app") == "CIDM":
                        return p, ""
        except Exception:
            pass
    return None, ""


def find_running_instance_port() -> int | None:
    """Find which port (if any) an existing CIDM instance is actively listening on."""
    port, _ = get_running_bridge_info()
    return port


def is_already_running() -> int | None:
    """Check if another CIDM instance is already running and listening on any bridge port."""
    return find_running_instance_port()


def request_focus_existing(port: int | None = None) -> None:
    """Ask the existing CIDM instance to restore its main window."""
    target_port, token = get_running_bridge_info()
    target_port = port or target_port or PORT
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-CIDM-Token"] = token
        req = urllib.request.Request(
            f"http://{HOST}:{target_port}/focus",
            data=b"{}",
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.5):
            pass
    except Exception:
        pass


def forward_url_to_running(url: str, port: int | None = None) -> bool:
    """Forward a download URL from CLI to the already-running CIDM instance."""
    target_port, token = get_running_bridge_info()
    target_port = port or target_port or PORT
    try:
        data = json.dumps({"url": url}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-CIDM-Token"] = token
        req = urllib.request.Request(
            f"http://{HOST}:{target_port}/add-download",
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> int:
    # Single-instance guard: if an instance is already running, forward URLs or focus and exit
    if "--force" not in sys.argv and "--restart" not in sys.argv:
        running_port = is_already_running()
        if running_port is not None:
            url_args = [
                arg for arg in sys.argv[1:]
                if not arg.startswith("-") and (arg.startswith("http://") or arg.startswith("https://"))
            ]
            if url_args:
                for u in url_args:
                    forward_url_to_running(u, running_port)
                request_focus_existing(running_port)
                print(f"Forwarded {len(url_args)} download(s) to running CIDM instance on port {running_port}.")
                return 0
            print(
                f"CIDM is already running in background/tray on port {running_port}. Bringing window to focus...")
            print("To force start a new instance, run: python main.py --force")
            request_focus_existing(running_port)
            return 0

    app = QApplication(sys.argv)
    app.setApplicationName("CIDM")
    app.setOrganizationName("CIDM")
    app.setFont(QFont("Segoe UI", 9))
    # Keep the event loop running even when all windows are hidden into the tray
    app.setQuitOnLastWindowClosed(False)

    app_icon = create_app_icon()
    app.setWindowIcon(app_icon)

    settings = load_settings()
    signals = BridgeSignals()
    window = MainWindow()
    window.apply_theme(settings.get("theme", "Dark Grey"))

    signals.download_requested.connect(window.handle_intercepted_download)
    signals.batch_requested.connect(window.handle_batch_requested)
    signals.focus_requested.connect(window.show_and_activate)
    signals.quit_requested.connect(window.quit_app)

    server = BridgeServer(signals)
    try:
        server.start()
        logging.info("CIDM bridge server listening on %s:%d", server.host, server.port)
    except OSError as exc:
        QMessageBox.warning(
            window,
            "Browser integration unavailable",
            f"Could not listen on any local bridge port ({exc}).\n\n"
            "Another process or security policy may be blocking local socket access. "
            "CIDM will work, but browser downloads cannot be intercepted.",
        )
    app.aboutToQuit.connect(server.stop)

    # Let Ctrl+C in a console quit cleanly (Qt's loop otherwise swallows SIGINT).
    signal.signal(signal.SIGINT, lambda *_: window.quit_app())
    _sigint_timer = QTimer()
    _sigint_timer.start(500)           # wake the interpreter so the handler runs
    _sigint_timer.timeout.connect(lambda: None)

    # Launch straight to system tray if requested via CLI or persistent settings
    start_minimized = "--minimized" in sys.argv or bool(
        settings.get("start_minimized", False)
    )
    if not start_minimized:
        window.show_and_activate()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
