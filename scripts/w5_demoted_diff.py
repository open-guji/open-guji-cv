# -*- coding: utf-8 -*-
"""W5 验收脚本（GUJI-49）：比「基线 seed_admit 产物」与「W5 分支同参数产物」。

用法：python scripts/w5_demoted_diff.py <基线产物根> <W5 产物根> <册> [<册>…]   （只读；不写任何东西）
  产物路径 <根>/<册>/seed_admit/pNNNN.json。

判据（两条都要过，退出码 0）：
  ① 把 W5 产物里每个 `evidence.demoted_from` 键去掉后，与基线**逐页相等**（逐字节：两边都按同一规则重序列化后比；
     关着所有降级开关时 W5 产物根本不含该键，应原样相等＝0 字节差）。
  ② 每个 `demoted_from` 都落在 admit=False、channel=None 的格上，且形如 {"channel": str|None, "by": str}。
输出：逐页不同的页数、demoted_from 个数（按 by 分）。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def _strip(o, found: list):
    if isinstance(o, dict):
        if isinstance(o.get("evidence"), dict) and "demoted_from" in o["evidence"]:
            found.append(o)
        return {k: (_strip(v, found) if not (k == "evidence" and isinstance(v, dict)) else
                    {ek: _strip(ev, found) for ek, ev in v.items() if ek != "demoted_from"})
                for k, v in o.items()}
    if isinstance(o, list):
        return [_strip(x, found) for x in o]
    return o


def _dump(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compare(a_root: Path, b_root: Path, book: str) -> dict:
    a_dir, b_dir = Path(a_root) / book / "seed_admit", Path(b_root) / book / "seed_admit"
    pages = sorted(p.name for p in a_dir.glob("p*.json"))
    diff_pages, by, bad = [], Counter(), []
    missing = [n for n in pages if not (b_dir / n).exists()]
    for n in pages:
        if n in missing:
            continue
        a = json.loads((a_dir / n).read_text(encoding="utf-8"))
        b = json.loads((b_dir / n).read_text(encoding="utf-8"))
        found: list = []
        b2 = _strip(b, found)
        if _dump(a) != _dump(b2):
            diff_pages.append(n)
        for rec in found:
            d = rec["evidence"]["demoted_from"]
            ok = (not rec.get("admit") and rec.get("channel") is None and isinstance(d, dict)
                  and set(d) == {"channel", "by"} and isinstance(d["by"], str))
            by[d.get("by") if isinstance(d, dict) else "?"] += 1
            if not ok:
                bad.append((n, rec.get("id")))
    return {"book": book, "pages": len(pages), "missing": missing, "diff_pages": diff_pages,
            "demoted_from": dict(by), "bad": bad}


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    rc = 0
    for book in argv[3:]:
        r = compare(Path(argv[1]), Path(argv[2]), book)
        print(json.dumps(r, ensure_ascii=False))
        if r["diff_pages"] or r["bad"] or r["missing"]:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
