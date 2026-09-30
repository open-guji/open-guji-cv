#!/usr/bin/env python3
"""overview#266 vol03 云端重算账：旧快照 vs 新产物，逐步数「字节变了的页」、Step3/4「变了的列/格」、
引擎日志里的实际运行页数与格级复用数、各步耗时（manifest `elapsed`，只算本轮重写的条目）。

用法：python recompute_report.py <旧 products 根> <新 products 根> <pipeline 日志>
"""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

BOOK = "vol03"


def manifest(root: Path, step: str) -> dict:
    f = root / BOOK / step / "_manifest.jsonl"
    out = {}
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                out[e["key"]] = e
    return out


def sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def cols_of(root: Path, step: str, key: str, kind: str):
    p = root / BOOK / step / f"{key}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text())[kind]
    out = {}
    for c in d.get("columns", []):
        cells = c.get("cells", c.get("chars", []))
        out[c.get("col")] = [json.dumps(x, sort_keys=True) for x in cells]
    return out


def main(old: str, new: str, log: str) -> None:
    old, new = Path(old), Path(new)
    text = Path(log).read_text(errors="replace")
    ran = Counter(m.group(1) for m in re.finditer(r"\] +\d+% (\w+) p\d+: 完成", text))
    ran_par = Counter(m.group(1) for m in re.finditer(r"^(\w+) p\d+: 完成", text, re.M))
    reuse = {}
    for m in re.finditer(r"(\w+) p(\d+): 复用 (\d+)/(\d+) 格", text):
        reuse.setdefault(m.group(1), []).append((int(m.group(3)), int(m.group(4))))
    steps = [s.name for s in sorted((new / BOOK).iterdir()) if (s / "_manifest.jsonl").exists()]
    rep = {}
    for st in steps:
        mo, mn = manifest(old, st), manifest(new, st)
        rewritten = [k for k in mn if mo.get(k, {}).get("ts") != mn[k].get("ts")]
        changed = [k for k in mn if sha(old / BOOK / st / f"{k}.json") != sha(new / BOOK / st / f"{k}.json")]
        r = {"pages_rewritten": len(rewritten), "pages_bytes_changed": len(changed),
             "elapsed_min": round(sum((mn[k].get("elapsed") or 0) for k in rewritten) / 60, 2),
             "log_ran": ran.get(st, 0) + ran_par.get(st, 0)}
        if st in reuse:
            r["cells_reused"] = sum(a for a, _ in reuse[st])
            r["cells_total_on_reused_pages"] = sum(b for _, b in reuse[st])
            r["pages_with_reuse"] = len(reuse[st])
        if st in ("row_segment", "cell_shrink"):
            kind = "cells" if st == "row_segment" else "char_index"
            ncol = ncell = 0
            pages = []
            for k in changed:
                a, b = cols_of(old, st, k, kind), cols_of(new, st, k, kind)
                cc = [c for c in set(a) | set(b) if a.get(c) != b.get(c)]
                if cc:
                    pages.append(k)
                ncol += len(cc)
                for c in cc:
                    x, y = a.get(c, []), b.get(c, [])
                    ncell += sum(1 for i in range(max(len(x), len(y)))
                                 if (x[i] if i < len(x) else None) != (y[i] if i < len(y) else None))
            r.update({"cols_changed": ncol, "cells_changed": ncell, "pages_with_col_change": len(pages)})
        rep[st] = r
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
