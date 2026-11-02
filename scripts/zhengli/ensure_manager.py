# -*- coding: utf-8 -*-
"""整理脚本开工时确保 guji-manager 装好、跟到 main（拆分 P2，2026-11-02）。

`guji source`／`cellvotes`／`freeze` 等命令陆续搬去 guji-manager（计划见 `doc/design/拆分-pipeline与manager.md`），
auto_cycle、proof_cycle、republish 经 `python -m open_guji_cv.cli_v2` 调它们，所以开工先调 `ensure()`。
云端（有 /opt/guji-venv，或设了 GUJI_MANAGER_DIR）复用 `scripts/ensure_manager.sh`：每 10 分钟最多拉一次 main，缺了当场装；
别的机器（本地 Windows 等）不动手，只在没装或太旧时提示。一律只警告、不拦。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SH = Path(__file__).resolve().parents[1] / "ensure_manager.sh"


def _installed() -> bool:
    import importlib.util
    return importlib.util.find_spec("guji_manager") is not None


def ensure() -> None:
    cloud = os.environ.get("GUJI_MANAGER_DIR") or Path("/opt/guji-venv").is_dir()
    bash = shutil.which("bash")
    if cloud and bash and SH.is_file():
        env = {**os.environ, "GUJI_MANAGER_PY": os.environ.get("GUJI_MANAGER_PY", sys.executable)}
        subprocess.run([bash, "-c", f'. "{SH.as_posix()}" && ensure_manager'], env=env, check=False)
        return
    if not _installed():
        print("ⓘ 没装 guji-manager：搬走的命令（如 guji opinions）会提示装法。"
              "装法：git clone --depth 1 https://github.com/open-guji/guji-manager <目录> && pip install --no-deps -e <目录>",
              file=sys.stderr)


if __name__ == "__main__":
    ensure()
