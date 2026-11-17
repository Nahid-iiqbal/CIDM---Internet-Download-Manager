"""build_app.py - Automated packaging script for CIDM.

1. Generates assets/cidm.ico if not already present.
2. Locates ffmpeg.exe (vendor/, vendor/bin/, or system PATH) and bundles it via --add-binary.
3. Bundles any adjacent FFmpeg shared DLLs for dynamic builds.
4. Runs PyInstaller in --onedir mode to produce a clean dist/CIDM/ distribution.
5. Supports optional direct Inno Setup compilation via --installer.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_base_dir() -> Path:
    return Path(__file__).resolve().parent


def ensure_icon(base_dir: Path) -> Path:
    assets_dir = base_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    ico_path = assets_dir / "cidm.ico"
    svg_path = assets_dir / "cidm.svg"
    legacy_ico = assets_dir / "pyidm.ico"

    if ico_path.exists() and ico_path.stat().st_size > 0:
        return ico_path
    if legacy_ico.exists() and legacy_ico.stat().st_size > 0:
        try:
            shutil.copy2(legacy_ico, ico_path)
            return ico_path
        except Exception:
            return legacy_ico

    print(f"[*] Generating multi-size Windows icon: {ico_path}")
    if svg_path.exists():
        import struct
        qt_core = __import__("PySide6.QtCore", fromlist=("QByteArray", "QBuffer", "QIODevice"))
        qt_gui = __import__("PySide6.QtGui", fromlist=("QImage", "QPainter", "QGuiApplication"))
        qt_svg = __import__("PySide6.QtSvg", fromlist=("QSvgRenderer",))
        app = qt_gui.QGuiApplication.instance() or qt_gui.QGuiApplication(sys.argv)
        renderer = qt_svg.QSvgRenderer(qt_core.QByteArray(svg_path.read_bytes()))

        def render_png(sz: int) -> bytes:
            img = qt_gui.QImage(sz, sz, qt_gui.QImage.Format.Format_ARGB32)
            img.fill(0)
            p = qt_gui.QPainter(img)
            p.setRenderHint(qt_gui.QPainter.RenderHint.Antialiasing)
            p.setRenderHint(qt_gui.QPainter.RenderHint.SmoothPixmapTransform)
            renderer.render(p)
            p.end()
            buf = qt_core.QBuffer()
            buf.open(qt_core.QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "PNG")
            return bytes(buf.data())

        sizes = [256, 128, 64, 48, 32, 16]
        png_map = {s: render_png(s) for s in sizes}
        header = struct.pack("<HHH", 0, 1, len(png_map))
        entries = []
        offset = 6 + 16 * len(png_map)
        image_data = b""
        for size, data in png_map.items():
            w = size if size < 256 else 0
            h = size if size < 256 else 0
            entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
            entries.append(entry)
            image_data += data
            offset += len(data)
        ico_bytes = header + b"".join(entries) + image_data
        ico_path.write_bytes(ico_bytes)
        try:
            shutil.copy2(ico_path, legacy_ico)
        except Exception:
            pass
        return ico_path


def find_or_bundle_ffmpeg(base_dir: Path) -> Path | None:
    """Check for ffmpeg in vendor/, vendor/bin/, or copy it from system PATH."""
    vendor_dir = base_dir / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    for cand in (vendor_dir / exe_name, vendor_dir / "bin" / exe_name):
        if cand.is_file():
            print(f"[+] Found FFmpeg in vendor: {cand}")
            return cand

    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        vendor_ffmpeg = vendor_dir / exe_name
        print(f"[*] Found system FFmpeg: {sys_ffmpeg}")
        try:
            print(f"[*] Copying system FFmpeg to vendor: {vendor_ffmpeg}")
            shutil.copy2(sys_ffmpeg, vendor_ffmpeg)
            return vendor_ffmpeg
        except Exception as e:
            print(f"[!] Warning: Could not copy system FFmpeg: {e}")
            return Path(sys_ffmpeg)

    print("[!] Warning: ffmpeg not found on PATH or in vendor/. Output will not include bundled ffmpeg.")
    return None


def terminate_running_instances() -> None:
    """Terminate any running CIDM or pyidm processes locking dist/ files."""
    if os.name != "nt":
        return
    for proc_name in ("CIDM.exe", "cidm.exe", "pyidm.exe", "PyIDM.exe"):
        try:
            subprocess.run(
                ["taskkill.exe", "/F", "/IM", proc_name, "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    import time
    time.sleep(0.5)


def clean_build_artifacts(base_dir: Path) -> None:
    print("[*] Terminating any running CIDM background instances...")
    terminate_running_instances()

    print("[*] Cleaning previous build artifacts...")
    import stat

    def _on_rm_error(func, path, exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    for folder in ("build", "dist"):
        p = base_dir / folder
        if p.exists():
            try:
                shutil.rmtree(p, onexc=_on_rm_error)
                print(f"    Removed {p}")
            except Exception as e:
                print(f"    Warning: Could not remove {p}: {e}")
    for spec in base_dir.glob("*.spec"):
        try:
            spec.unlink()
            print(f"    Removed {spec}")
        except Exception as e:
            print(f"    Warning: Could not remove {spec}: {e}")


def find_inno_setup_compiler() -> Path | None:
    """Find Inno Setup compiler (ISCC.exe) on the system."""
    cmd = shutil.which("iscc") or shutil.which("ISCC")
    if cmd:
        return Path(cmd)

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    candidates = [
        Path(local_app_data) / r"Programs\Inno Setup 6\ISCC.exe",
        Path(program_files_x86) / r"Inno Setup 6\ISCC.exe",
        Path(program_files) / r"Inno Setup 6\ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def run_inno_setup(base_dir: Path) -> int:
    iscc = find_inno_setup_compiler()
    iss_file = base_dir / "installer.iss"

    if not iss_file.exists():
        print(f"[!] Inno Setup script not found: {iss_file}")
        return 1

    if not iscc:
        print(
            "[!] Inno Setup 6 (ISCC.exe) not found on PATH or standard program directories.")
        print("    Install it via: winget install JRSoftware.InnoSetup")
        print(f"    Then compile manually: ISCC.exe {iss_file}")
        return 1

    print(f"\n[*] Compiling installer using {iscc}...")
    res = subprocess.run([str(iscc), str(iss_file)])
    if res.returncode == 0:
        out_setup = base_dir / "Output" / "CIDM_Setup.exe"
        print("\n" + "=" * 65)
        print("[+] Windows Installer compiled successfully:")
        print(f"    {out_setup}")
        print("=" * 65)
    return res.returncode


def build(
    onedir: bool = True,
    clean: bool = True,
    compile_installer: bool = False,
) -> int:
    base_dir = get_base_dir()

    if clean:
        clean_build_artifacts(base_dir)

    ico_path = ensure_icon(base_dir)
    ffmpeg_path = find_or_bundle_ffmpeg(base_dir)

    entry_point = base_dir / "main.py"
    if not entry_point.exists():
        print(f"[!] Entry point not found: {entry_point}")
        return 1

    print("\n[*] Building CIDM desktop app...")
    print(f"    Entry Point: {entry_point}")
    print(
        f"    Mode: {'Folder Bundle (--onedir for Inno Setup)' if onedir else 'Single File (--onefile)'}"
    )

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(entry_point),
        "--name=CIDM",
        "--noconsole",
        "--clean",
        "--noconfirm",
        f"--icon={str(ico_path)}",
        # Explicit hidden imports
        "--hidden-import=engine",
        "--hidden-import=server",
        "--hidden-import=ui",
        "--hidden-import=grabber",
        "--hidden-import=updater",
        "--hidden-import=yt_dlp",
        "--hidden-import=yt_dlp.compat",
        "--hidden-import=yt_dlp.utils",
        "--hidden-import=yt_dlp.extractor",
        "--hidden-import=PySide6",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        "--hidden-import=requests",
        "--hidden-import=cryptography",
        # Collect yt-dlp dependencies
        "--collect-all=yt_dlp",
        "--collect-submodules=yt_dlp",
    ]

    if onedir:
        cmd.append("--onedir")
    else:
        cmd.append("--onefile")

    sep = ";" if os.name == "nt" else ":"
    assets_dir = base_dir / "assets"
    if assets_dir.exists():
        cmd.append(f"--add-data={str(assets_dir)}{sep}assets")
    if ico_path and ico_path.exists():
        cmd.append(f"--add-data={str(ico_path)}{sep}.")

    chrome_ext_dir = base_dir / "chrome_extension"
    if chrome_ext_dir.exists():
        cmd.append(f"--add-data={str(chrome_ext_dir)}{sep}chrome_extension")
        cmd.append(f"--add-data={str(chrome_ext_dir)}{sep}extension{os.sep}chromium")

    firefox_ext_dir = base_dir / "firefox_extension"
    if firefox_ext_dir.exists():
        cmd.append(f"--add-data={str(firefox_ext_dir)}{sep}firefox_extension")
        cmd.append(f"--add-data={str(firefox_ext_dir)}{sep}extension{os.sep}firefox")

    # Add bundled ffmpeg binary directly to output root
    if ffmpeg_path and ffmpeg_path.exists():
        cmd.append(f"--add-binary={str(ffmpeg_path)}{sep}.")
        print(f"    Bundling FFmpeg: {ffmpeg_path} -> .")

        # Check ffmpeg_path.parent for adjacent shared DLLs (dynamic/MSYS2/MinGW builds)
        ffmpeg_dir = ffmpeg_path.parent
        dll_patterns = [
            "avcodec-*.dll", "avformat-*.dll", "avutil-*.dll",
            "swresample-*.dll", "swscale-*.dll", "avfilter-*.dll",
            "avdevice-*.dll", "libgcc_*.dll", "libstdc++-*.dll",
            "libwinpthread-*.dll", "zlib1.dll", "*.dll",
        ]
        bundled_dlls = set()
        for pat in dll_patterns:
            for dll_file in ffmpeg_dir.glob(pat):
                if dll_file.is_file() and dll_file.name not in bundled_dlls:
                    bundled_dlls.add(dll_file.name)
                    cmd.append(f"--add-binary={str(dll_file)}{sep}.")
                    print(
                        f"    Bundling FFmpeg dependency DLL: {dll_file.name} -> ."
                    )

    print("\n[*] Invoking PyInstaller...")
    ret = subprocess.run(cmd)
    if ret.returncode != 0:
        print(f"[!] PyInstaller build failed with exit code {ret.returncode}")
        return ret.returncode

    dist_dir = base_dir / "dist" / "CIDM" if onedir else base_dir / "dist"

    if onedir and dist_dir.exists():
        print("[*] Copying assets and browser extension packages to distribution directory...")
        assets_dist = dist_dir / "assets"
        if assets_dist.is_file():
            assets_dist.unlink()
        assets_dist.mkdir(parents=True, exist_ok=True)
        if assets_dir.exists():
            for f in assets_dir.iterdir():
                if f.is_file():
                    shutil.copy2(f, assets_dist / f.name)
            print("    Copied assets folder -> dist/CIDM/assets")

        if chrome_ext_dir.exists():
            shutil.copytree(chrome_ext_dir, dist_dir / "extension" / "chromium", dirs_exist_ok=True)
            shutil.copytree(chrome_ext_dir, dist_dir / "extension", dirs_exist_ok=True)
            shutil.copytree(chrome_ext_dir, dist_dir / "chrome_extension", dirs_exist_ok=True)
            print("    Copied Chromium extension -> dist/CIDM/extension/chromium and dist/CIDM/chrome_extension")
        if firefox_ext_dir.exists():
            shutil.copytree(firefox_ext_dir, dist_dir / "extension" / "firefox", dirs_exist_ok=True)
            shutil.copytree(firefox_ext_dir, dist_dir / "firefox_extension", dirs_exist_ok=True)
            print("    Copied Firefox extension -> dist/CIDM/extension/firefox and dist/CIDM/firefox_extension")

    print("\n" + "=" * 65)
    print("[+] PyInstaller build completed successfully:")
    print(f"    Directory: {dist_dir}")
    print("=" * 65)

    if compile_installer:
        return run_inno_setup(base_dir)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build CIDM distribution and Windows installer."
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single standalone .exe instead of a --onedir folder.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean build/ and dist/ before starting the build.",
    )
    parser.add_argument(
        "--installer",
        action="store_true",
        help="Automatically compile CIDM_Setup.exe using Inno Setup (ISCC.exe) after PyInstaller finishes.",
    )

    args = parser.parse_args()
    return build(
        onedir=not args.onefile,
        clean=not args.no_clean,
        compile_installer=args.installer,
    )


if __name__ == "__main__":
    sys.exit(main())
