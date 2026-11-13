"""code_equiv 登记「只增不减」检查：工作区的 ENTRIES 对给定的每个参照版本（分支／tag／提交）都不能丢链。

    python scripts/check_code_equiv_monotonic.py origin/dev v0.7.18 v0.7.24

做法：对每个参照版本，取它登记里出现过的每个 (模块, 哈希)（new 和 old 都算），比较「参照版本的链走到头」与
「工作区的链走到头」；不同就是工作区丢了登记或接错了链（该参照版本出的产物，在工作区这版会被判过期）。
两条线对同一个 new 登了不同的 old（patch 线与 dev 线）不算错，只要走到头的规范值一致。退出码 1＝有丢链。

什么时候跑：任何把 rc／patch 线合回 dev（`-s ours`）之后、合 PR 之前，参照至少给 `origin/dev`（合并前）和被合回的 rc。
**别用 `git checkout <rc> -- code_equiv.py` 整份覆盖**（#1488 就这样把 dev 的 4 条登记覆盖掉了）：只把 rc 上新增的行追加进 dev 的文件。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL = "open_guji_cv/core/code_equiv.py"
PAT = re.compile(r"Equiv\(module='([^']+)',\s*new='([0-9a-f]+)',\s*old='([0-9a-f]+)'")


def table(src: str) -> dict[str, dict[str, str]]:
    t: dict[str, dict[str, str]] = {}
    for m, n, o in PAT.findall(src):       # 同 code_equiv._table：同一个 new 后登记的覆盖先登记的
        t.setdefault(m, {})[n] = o
    return t


def canon(t: dict, m: str, h: str) -> str:
    mm, seen = t.get(m, {}), set()
    while h in mm and h not in seen:
        seen.add(h)
        h = mm[h]
    return h


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cur = table((ROOT / REL).read_text(encoding="utf-8"))
    bad = 0
    for ref in argv:
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:{REL}"], capture_output=True, text=True)
        if r.returncode:
            print(f"✗ 读不到 {ref}:{REL}")
            return 2
        old = table(r.stdout)
        lost = sorted({(m, h) for m, d in old.items() for h in [*d, *d.values()] if canon(old, m, h) != canon(cur, m, h)})
        for m, h in lost:
            print(f"✗ {ref}：{m} {h[:8]} 在 {ref} 走到 {canon(old, m, h)[:8]}，工作区走到 {canon(cur, m, h)[:8]}")
        bad += len(lost)
        if not lost:
            print(f"✓ {ref}：登记链都接得上")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
