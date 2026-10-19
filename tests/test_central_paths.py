"""守卫（GUJI-608）：中心库管的数据（books/ feedback/ review/ config/ 字形库）不许从工作区根直接拼路径。

迁到中心库后这些数据在工作区外的数据目录，路径一律走 ``core.workspace``（``data_root``、``books_dir``、
``ws_config_dir``、``feedback_root``、``glyph_store_path`` …），否则迁过的工作区上会静默读空。
"""
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "open_guji_cv"
PAT = re.compile(r'\b(ws|ws_dir|workspace|wsdir|ws_root|workspace_root\(\))\s*\)?\s*/\s*"(books|feedback|review|config)"')
ALLOW = {
    "snap/importer.py",            # 从快照新建工作区（建空 books/）
}


def test_no_direct_workspace_data_paths():
    bad = []
    for f in sorted(PKG.rglob("*.py")):
        rel = f.relative_to(PKG).as_posix()
        if rel.startswith("datastore/") or rel == "core/workspace.py" or rel in ALLOW:
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if PAT.search(line):
                bad.append(f"{rel}:{i}: {line.strip()}")
    assert not bad, "改走 core.workspace 的路径函数：\n" + "\n".join(bad)
