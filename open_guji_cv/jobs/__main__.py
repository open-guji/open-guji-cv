"""`python -m open_guji_cv.jobs` → guji-manager 的 `guji_manager.jobs`（拆分 P3，2026-11-04）。

任务库的执行方与命令（runner、cli、board…）已搬去 guji-manager。这里只转发，给还在用老命令行的执行方
（`os.execv(sys.orig_argv)` 空闲换代码时沿用原命令行）和老脚本；新的一律 `python -m guji_manager.jobs`。
没装 manager 时先试 `scripts/zhengli/ensure_manager.py`（云端会当场装），还不行就给装法、退出码 2。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _load():
    try:
        from guji_manager.jobs.cli import main
        return main
    except ImportError:
        return None


main = _load()
if main is None:
    em = Path(__file__).resolve().parents[2] / "scripts" / "zhengli"
    if (em / "ensure_manager.py").is_file():
        sys.path.insert(0, str(em))
        from ensure_manager import ensure
        ensure()
        main = _load()
if main is None:
    print("任务库（jobs）已搬到 guji-manager（拆分 P3，2026-11-04），本机没装或版本低于 0.3.2。"
          "装法：git clone --depth 1 https://github.com/open-guji/guji-manager <目录> && pip install --no-deps -e <目录>"
          "（云端：uv pip install --python /opt/guji-venv/bin/python …）；之后用 python -m guji_manager.jobs。", file=sys.stderr)
    sys.exit(2)
main()
