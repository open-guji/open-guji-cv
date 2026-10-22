"""L2 表 Sonnet 异议改表：表里主模型（haiku）给了字、Sonnet 以 high 给了组内另一个字 → 以 Sonnet 为准。

日曰表里这类格共 5 个（vol06:134:2:14、vol07:24:1:13、vol07:85:4:5、vol07:124:3:8、vol10:91:3:8），
长上下文逐格读原典核过：Sonnet 5/5 对、haiku 5/5 错（2026-10-22，见 doc/research/己已巳日曰日目-送审收口-2026-10-22.md 第四轮）。
只改表文件，不动 Step 代码，所以不影响 seed_admit 的 code_hash。

用法：python scripts/l2_apply_dissent.py <表.json> <输出.json> [--judge sonnet] [--members 日曰]
"""
from __future__ import annotations

import argparse
import json


def apply_dissent(table: dict, judge: str = "sonnet", members: str | None = None) -> list[str]:
    changed = []
    for cid, e in (table.get("cells") or {}).items():
        v = (e.get("votes") or {}).get(judge)
        if e.get("char") is None or not v or v[1] != "high" or v[0] == e["char"]:
            continue
        if members is not None and v[0] not in members:
            continue
        e["char"], e["why"] = v[0], "agree:dissent"
        e.pop("strong", None)
        changed.append(cid)
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--judge", default="sonnet")
    ap.add_argument("--members", default=None)
    a = ap.parse_args()
    t = json.load(open(a.src, encoding="utf-8"))
    ch = apply_dissent(t, a.judge, a.members)
    json.dump(t, open(a.dst, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"改 {len(ch)} 格：", " ".join(ch))


if __name__ == "__main__":
    main()
