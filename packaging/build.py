#!/usr/bin/env python3
"""
Build script for guji-cv standalone executable.

Usage:
    python packaging/build.py        # build guji-cv-ui
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"

IS_WIN = sys.platform == "win32"
EXE_SUFFIX = ".exe" if IS_WIN else ""


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, shell=IS_WIN)
    if result.returncode != 0:
        sys.exit(result.returncode)


def build_ui() -> None:
    name = f"guji-cv-ui{EXE_SUFFIX}"
    print(f"\n-- Building {name} --")

    # Verify web UI exists
    html = ROOT / "open_guji_cv" / "web" / "index.html"
    if not html.exists():
        print(f"Error: Web UI not found: {html}")
        sys.exit(1)

    run([
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "ui"),
        "--noconfirm",
        str(PACKAGING / "ui.spec"),
    ])
    print(f"  Output: {DIST / name}")


def main() -> None:
    DIST.mkdir(exist_ok=True)
    build_ui()

    print("\nDone.")
    for f in sorted(DIST.glob("guji-cv*")):
        if f.suffix in ("", ".exe"):
            size_mb = f.stat().st_size / 1024 / 1024
            print(f"  {f.name}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
