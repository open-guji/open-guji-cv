# -*- coding: utf-8 -*-
"""比对两份 products 的 seed_admit/_manifest.jsonl：params_hash、fingerprint、上游指纹。只读。

    python manifest_cmp.py <交付态products根> <重落后products根> <册>
        [--expect-params 7347f2f885382c6d]    # vol01 标准字形库口径的 params_hash（9587e67c）
        [--fp-json fp_after.json --fp-ref fp_ref.json]   # fp_dump.py 的 19 步 code_hash 输出，逐步比对
输出：params_hash 集合（前/后）、与 expect 是否一致、fingerprint 不同页数、上游指纹变化；退出码 0=全一致 1=有差异。
判读：params_hash 变 → 配置或字形库变了（改 shadow_veto 必变，先说明）；code_hash 不同 → 代码不是同一棵树，停下问。
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def rows(root, book):
    p = Path(root) / book / "seed_admit" / "_manifest.jsonl"
    if not p.is_file():
        sys.exit(f"没有 {p}")
    return {r["key"]: r for r in map(json.loads, p.read_text(encoding="utf-8").splitlines() if p.stat().st_size else [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before"); ap.add_argument("after"); ap.add_argument("book")
    ap.add_argument("--expect-params"); ap.add_argument("--fp-json"); ap.add_argument("--fp-ref")
    a = ap.parse_args()
    b, n = rows(a.before, a.book), rows(a.after, a.book)
    ph = lambda d: dict(Counter(r.get("params_hash") for r in d.values()))
    print(f"页数 前{len(b)} 后{len(n)}；params_hash 前{ph(b)} 后{ph(n)}")
    bad = 0
    if a.expect_params:
        ok = set(ph(n)) == {a.expect_params}
        print(f"后 params_hash == {a.expect_params}：{'是' if ok else '否 ✗'}"); bad |= not ok
    fpd = sum(1 for k in n if k in b and b[k].get("fingerprint") != n[k].get("fingerprint"))
    shd = sum(1 for k in n if k in b and b[k].get("sha256") != n[k].get("sha256"))
    up = Counter()
    for k in n:
        if k in b:
            for s, v in (n[k].get("upstream") or {}).items():
                if (b[k].get("upstream") or {}).get(s) != v:
                    up[s] += 1
    print(f"fingerprint 不同页 {fpd}；产物 sha256 不同页 {shd}；上游指纹变化(步:页数) {dict(up)}")
    bad |= bool(fpd)
    if a.fp_json and a.fp_ref:
        x, y = json.load(open(a.fp_json)), json.load(open(a.fp_ref))
        diff = [k for k in set(x) | set(y) if x.get(k) != y.get(k)]
        print(f"code_hash 逐步比对：不同 {len(diff)} 步 {sorted(diff)}"); bad |= bool(diff)
    return int(bool(bad))


sys.exit(main())
