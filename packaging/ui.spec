# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for guji-cv-ui executable.
Bundles web UI (index.html) + all analyzers.
Double-click to launch browser UI at http://localhost:8632.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
WEB_DIR = ROOT / 'open_guji_cv' / 'web'

if not (WEB_DIR / 'index.html').exists():
    raise FileNotFoundError(f"Web UI not found: {WEB_DIR / 'index.html'}")

a = Analysis(
    [str(ROOT / 'open_guji_cv' / 'web' / '_entry.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Bundle the web UI HTML
        (str(WEB_DIR / 'index.html'), 'open_guji_cv/web'),
    ],
    hiddenimports=[
        # web module
        'open_guji_cv.web',
        'open_guji_cv.web.server',
        'open_guji_cv.web.runner',
        # core
        'open_guji_cv',
        'open_guji_cv.__main__',
        'open_guji_cv.pipeline',
        'open_guji_cv.profile',
        # analyzers
        'open_guji_cv.analyzers',
        'open_guji_cv.analyzers.base',
        'open_guji_cv.analyzers.color_mode',
        'open_guji_cv.analyzers.page_layout',
        'open_guji_cv.analyzers.interference',
        'open_guji_cv.analyzers.border_style',
        'open_guji_cv.analyzers.text_layout',
        'open_guji_cv.analyzers.font_type',
        'open_guji_cv.analyzers.cut_type',
        # preprocessors
        'open_guji_cv.preprocessors',
        # dependencies
        'numpy',
        'cv2',
        'PIL',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'PyQt5', 'wx',
        # PaddlePaddle/OCR too large for standalone — exclude
        'paddle', 'paddlepaddle', 'paddleocr',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='guji-cv-ui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # No console window — browser-only UI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
