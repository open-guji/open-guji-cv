"""服务器跑的是 Python 3.11（2026-09-27 值守实测 3.11.6），本机/云端是 3.12。

3.12 放宽了 f-string 语法（PEP 701：表达式里可以有反斜杠、同种引号、跨行），
这种写法在 3.12 下测试全绿，到服务器上却是 SyntaxError——`report/html.py`
就这样让 `guji collate` 在服务器上整条跑不了。本测试在装了 python3.11 的机器上
用它把全包编译一遍；没装就跳过（可选件缺席，不是数据依赖）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("python3.11") is None, reason="没装 python3.11")
def test_sources_compile_under_python311(tmp_path):
    # 编译产物写进 tmp，不往仓里留 __pycache__（conftest 的仓库卫生闸会查）
    code = (
        "import sys, py_compile, pathlib\n"
        "root = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2]); bad = []\n"
        "for d in ('open_guji_cv', 'scripts'):\n"
        "    for f in sorted((root / d).rglob('*.py')):\n"
        "        try:\n"
        "            py_compile.compile(str(f), cfile=str(out / 'x.pyc'), doraise=True)\n"
        "        except py_compile.PyCompileError as e:\n"
        "            bad.append(f'{f.relative_to(root)}: {e.msg.strip().splitlines()[-1]}')\n"
        "print('\\n'.join(bad)); sys.exit(1 if bad else 0)\n"
    )
    r = subprocess.run([shutil.which("python3.11"), "-c", code, str(ROOT), str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "这些文件在 Python 3.11 下编译不过：\n" + r.stdout + r.stderr
