"""doc/<N>-<大步>/步骤与产物.md 是从代码生成的；改了 Step 或产物定义没重跑生成脚本，这里报错。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stage_docs_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_stage_docs.py"), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_stage_readme_lists_every_step():
    """大步 README 的小步表要列全骨架 `stages:` 里的每个步骤 id（验收标准 B1，2026-11-28 用户定）。

    只查「README 里出现了 `<步骤 id>`」：新增、改名、挪大步的 Step 没写进对应 README 就报错。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_stage_docs as g

    missing = []
    for stage, d, _ in g.STAGES:
        text = (ROOT / "doc" / d / "README.md").read_text(encoding="utf-8")
        for sid in g._stage_steps()[stage]:
            if f"`{sid}`" not in text:
                missing.append(f"doc/{d}/README.md 缺 `{sid}`")
    assert not missing, "\n".join(missing)
