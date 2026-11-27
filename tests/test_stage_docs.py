"""doc/<N>-<大步>/步骤与产物.md 是从代码生成的；改了 Step 或产物定义没重跑生成脚本，这里报错。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stage_docs_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_stage_docs.py"), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
