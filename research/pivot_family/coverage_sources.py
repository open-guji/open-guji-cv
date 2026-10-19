# -*- coding: utf-8 -*-
"""异体族来源对比：本仓 variants.json / char-components rt（部件檢索）/ 字统网 yi 图，各自的覆盖与按图排序后的名次。

只读、不改引擎。接 pivot_family.py 的逐条结果（rows.jsonl.gz）和同一份 r5 模板索引。

    cd open-guji-cv && .venv/bin/python research/pivot_family/coverage_sources.py \
        --rows research/pivot_family/rows.jsonl.gz --zi-dir <字统网 /api/zi 缓存目录> \
        --rt <char-components web/data/rt.jsonl> --dt <同目录 dt.jsonl> --out <json>

两档靶子：
- V：刻本用了非常用异体（pivot_family 的 414 条，p 由本仓表定，所以本仓表覆盖恒为 100%——
  这里看的是另两家对同一批 (p, g) 的覆盖，以及换池后的名次）。
- N：金标 g 在本仓表里**没有任何异体边**的 oov/unseen 条。本仓对这批无能为力；看另两家能不能给出族，
  并以「族里整理本最常用的字」当 p，量 g 在 p 的族里按图排第几。
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def zi_family(doc: dict, q: str, max_hops: int = 1) -> set[str]:
    """字统网 /api/zi/<q> 的 yi 图：从字形=q 或正字=q 的节点出发，沿边走 max_hops 跳，收已编码单字。"""
    yi = doc.get("yi") or {}
    nodes = yi.get("nodes") or {}
    adj: dict[str, set[str]] = {}
    for a, b in yi.get("edges") or []:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    frontier = {k for k, n in nodes.items() if n[4] == q or n[10] == q}
    seen = set(frontier)
    for _ in range(max_hops):
        nxt = {m for k in frontier for m in adj.get(k, ()) if m not in seen}
        seen |= nxt
        frontier = nxt
    out = {nodes[k][4] for k in seen if k in nodes and isinstance(nodes[k][4], str)
           and len(nodes[k][4]) == 1}
    out.discard(q)
    return out


def load_rt(rt: Path, dt: Path) -> dict[str, set[str]]:
    """部件檢索：dt 每行首字是字头，rt 同行是展示用异体（「~」后为异体，无「~」是部件对应字）。无向。"""
    adj: dict[str, set[str]] = {}
    for a, b in zip(dt.read_text(encoding="utf-8").splitlines(), rt.read_text(encoding="utf-8").splitlines()):
        head = json.loads(a)[:1]
        vs = [c for c in json.loads(b).lstrip("~") if not c.isspace()]
        for v in vs:
            if v != head and head:
                adj.setdefault(head, set()).add(v)
                adj.setdefault(v, set()).add(head)
    return adj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--zi-dir", required=True)
    ap.add_argument("--rt", required=True)
    ap.add_argument("--dt", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    from open_guji_cv.clustering.rare_panel import _corpus_freq
    from open_guji_cv.steps.align_ref import DEFAULT_CORPUS
    from open_guji_cv.variants import NEVER_SOURCES, _graph

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pivot_family import load_items

    G = _graph()
    freq = _corpus_freq(DEFAULT_CORPUS)
    rt = load_rt(Path(a.rt), Path(a.dt))
    zi_cache: dict[str, dict | None] = {}

    def zi(c: str) -> set[str] | None:
        if c not in zi_cache:
            f = Path(a.zi_dir) / f"zi_{c}.json"
            try:
                zi_cache[c] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                zi_cache[c] = None
        d = zi_cache[c]
        return None if d is None else zi_family(d, c)

    def ours(c: str) -> set[str]:
        return {v for v, t in G.variants_of(c) if set(t) - NEVER_SOURCES}

    rows = [json.loads(l) for l in gzip.open(a.rows, "rt", encoding="utf-8")]
    cs = tuple(base_charset("unicode-cjk-ab"))
    cnn = CnnCandidates(str(DEFAULT_CKPT))
    cnn._ensure()
    mat, names = cnn._emb_index(cs)
    pos = {c: i for i, c in enumerate(names)}
    items = load_items(2621)
    assert len(items) == len(rows), (len(items), len(rows))
    Q = cnn.embed([im for _, _, im in items])

    def rank(i: int, pool: set[str], g: str) -> int | None:
        pool = [c for c in pool if c in pos]
        if g not in pool:
            return None
        s = mat[[pos[c] for c in pool]] @ Q[i]
        order = [pool[j] for j in np.argsort(-s)]
        return order.index(g) + 1

    out: dict = {}
    # ── V 档：同一批 (p, g)，换来源 ──
    V = [(i, r) for i, r in enumerate(rows) if r["pivot"] and not r["pivot_is_g"]]
    V = [(i, r) for i, r in V if zi(r["pivot"]) is not None]
    res = {}
    for name, fam in (("ours", lambda p: ours(p)),
                      ("rt", lambda p: rt.get(p, set())),
                      ("zi", lambda p: zi(p) or set()),
                      ("ours+rt", lambda p: ours(p) | rt.get(p, set())),
                      ("all3", lambda p: ours(p) | rt.get(p, set()) | (zi(p) or set()))):
        rk, sizes = [], []
        for i, r in V:
            pool = {r["pivot"]} | fam(r["pivot"])
            sizes.append(len(pool))
            rk.append(rank(i, pool, r["g"]))
        res[name] = {"n": len(V), "covered": sum(x is not None for x in rk),
                     **{f"top{k}": sum(1 for x in rk if x and x <= k) for k in (1, 3, 5, 10)},
                     "pool_median": float(np.median(sizes))}
    out["V"] = res
    # ── N 档：本仓表没边的 g ──
    N = [(i, r) for i, r in enumerate(rows) if not r["has_family"] and r["tier"] in ("oov", "unseen")]
    nres = {"n": len(N), "zi_fetched": 0, "zi_has_family": 0, "rt_has_family": 0, "detail": []}
    for i, r in N:
        g = r["g"]
        zf = zi(g)
        if zf is not None:
            nres["zi_fetched"] += 1
        fam = (zf or set()) | rt.get(g, set())
        nres["zi_has_family"] += bool(zf)
        nres["rt_has_family"] += bool(rt.get(g))
        if not fam:
            nres["detail"].append({"g": g, "family": 0})
            continue
        cand = [g] + sorted(fam)
        p = max(cand, key=lambda c: (freq.get(c, 0), c == g))
        pool = {p} | (zi(p) or set()) | rt.get(p, set()) | ours(p)
        nres["detail"].append({"g": g, "p": p, "family": len(fam), "pool": len(pool),
                               "rank": rank(i, pool, g), "base_rank": r["base_rank"]})
    hit = [d for d in nres["detail"] if d.get("p") and d["p"] != d["g"]]
    nres["p_ne_g"] = len(hit)
    for k in (1, 3, 5, 10):
        nres[f"p_ne_g_top{k}"] = sum(1 for d in hit if d["rank"] and d["rank"] <= k)
        nres[f"p_ne_g_base_top{k}"] = sum(1 for d in hit if d["base_rank"] and d["base_rank"] <= k)
    out["N"] = nres
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"V": out["V"], "N": {k: v for k, v in nres.items() if k != "detail"}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
