# -*- coding: utf-8 -*-
"""影子放行模型·信号抽取：每个 (字位, 候选) 一行信号，写 JSONL。

    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/experiments/shadow_admit/extract.py bxgb \
        --which labeled|all --out <ws>/reports/bxgb/shadow/signals_labeled.jsonl

计划见 overview `进度/Step7-放行判定/08-影子放行模型-计划.md`。不改任何产物。
- 标签：人裁 confirm（`feedback.lookup.human_chars`）+ Step8「我方对」（collate_ok，取当时我方字）。
- 库信号对**有 v2: 人裁实例的格**重算并摘除自身（生产 Step5-a 只摘不带前缀的 id，这些格会匹配到自己）。
- 小笔画判别器（总览/14 §八 方案③）只在库前两名异字都有人裁实例时算。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

S = 96
MAX_EX = 4


def _prep(g):
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    keep = np.zeros_like(b)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 6:
            keep[lab == i] = 255
    ys, xs = np.nonzero(keep)
    out = np.zeros((S, S), np.uint8)
    if len(ys) == 0:
        return out
    keep = keep[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = keep.shape
    k = (S - 8) / max(h, w)
    r = cv2.resize(keep, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) > 127
    y, x = (S - r.shape[0]) // 2, (S - r.shape[1]) // 2
    out[y:y + r.shape[0], x:x + r.shape[1]] = r
    return out


def _dt(b):
    return cv2.distanceTransform((1 - b).astype(np.uint8), cv2.DIST_L2, 3)


def chamfer(a, b):
    """刚性对齐（平移 ±5、缩放 3 档）后的对称倒角距离（97 分位，取较差一侧）。"""
    if not a.any() or not b.any():
        return 1e9
    da, best, bestbb = _dt(a), 1e9, None
    for sc in (0.94, 1.0, 1.06):
        bs = cv2.resize(b, None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)
        c = np.zeros((S, S), np.uint8)
        h, w = bs.shape
        y0, x0 = max(0, (h - S) // 2), max(0, (w - S) // 2)
        bs = bs[y0:y0 + S, x0:x0 + S]
        oy, ox = (S - bs.shape[0]) // 2, (S - bs.shape[1]) // 2
        c[oy:oy + bs.shape[0], ox:ox + bs.shape[1]] = bs
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                bb = np.roll(np.roll(c, dy, 0), dx, 1)
                if not bb.any():
                    continue
                s = float(np.percentile(da[bb > 0], 97))
                if s < best:
                    best, bestbb = s, bb
    if bestbb is None:
        return 1e9
    return max(best, float(np.percentile(_dt(bestbb)[a > 0], 97)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--which", default="labeled", choices=("labeled", "all"))
    ap.add_argument("--pages", default="3-56")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from open_guji_cv.clustering.candidates import traditional_candidates
    from open_guji_cv.clustering.confusable import partners as _partners
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.seeding import load_matcher_from_db
    from open_guji_cv.clustering.variants import VariantMap
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.feedback.lookup import human_chars
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.report.slots import page_slots
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    from open_guji_cv.utils.image_io import imread

    from open_guji_cv.core.book import load_book
    book = a.book
    NS = getattr(load_book(book), "norm_stroke", None)   # 与该书 Step5-a 同一把尺子（bxgb=3，四庫=None）
    st, cache, vm, partners = ProductStore(), ImageCache(), VariantMap.load(), _partners()

    # 标签
    labels = {k: v[0] for k, v in human_chars(book).items()}
    n_human = len(labels)
    for e in EventLog().iter_all():
        if e.kind == "collate_ok" and e.target.key.startswith(book + ":") and e.target.key not in labels:
            pair = (e.payload or {}).get("pair") or []
            if pair:
                labels[e.target.key] = pair[0]
    print(f"标签：人裁 {n_human}，复核我方对 {len(labels) - n_human}", file=sys.stderr)

    db_path = GlyphMatchParams().db_path
    db = GlyphDB(db_path)
    human_ids: dict[str, list[str]] = {}
    for ch, iid in db.conn.execute(
            """SELECT g.char, e.instance_id FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
               JOIN instances i ON i.instance_id=e.instance_id WHERE i.label_status='human'"""):
        human_ids.setdefault(ch, []).append(iid.replace("v2:", ""))
    v2_cells = {iid for ids in human_ids.values() for iid in ids}
    matcher = None

    def raw(cid):
        bk, p, c, s = cid.split(":")        # 人裁实例可能来自同工作区的别册（vol01 的实例给 vol02 用）
        sub = s[-1] if s[-1] in "ab" else ""
        s = s.rstrip("ab")
        path = cache.get(bk, "char_patch", f"p{int(p):04d}c{int(c):02d}s{s}{sub}")
        return None if path is None else imread(str(path), cv2.IMREAD_GRAYSCALE)

    prep_cache: dict[str, np.ndarray] = {}

    def prep(cid):
        if cid not in prep_cache:
            r = raw(cid)
            prep_cache[cid] = None if r is None else _prep(r)
        return prep_cache[cid]

    def disc(cid, ch):
        """本格对 ch 的人裁实例（摘自身）最近倒角距离；无实例 → None。"""
        a0 = prep(cid)
        if a0 is None:
            return None
        exs = [prep(e) for e in human_ids.get(ch, []) if e != cid][:MAX_EX * 2]
        ds = [chamfer(a0, b) for b in exs if b is not None][:MAX_EX]
        ds = [d for d in ds if d < 1e8]
        return min(ds) if ds else None

    lo, _, hi = a.pages.partition("-")
    out = open(a.out, "w", encoding="utf-8")
    n_cells = n_rows = n_uncovered = 0
    for pg in range(int(lo), int(hi or lo) + 1):
        key = page_key(pg)
        if not st.exists(book, "seed_admit", key):
            continue
        gm = {r["id"]: r for c in st.read(book, "glyph_match", key, "glyph_match").model_dump()["columns"]
              for r in (c.get("chars") or [])}
        oc = {r["id"]: r for c in st.read(book, "ocr_candidates", key, "ocr_candidates").model_dump()["columns"]
              for r in (c.get("chars") or [])}
        rc = {r["id"]: r for c in st.read(book, "rare_candidates", key, "rare_candidates").model_dump()["columns"]
              for r in (c.get("chars") or [])}
        al = {r["id"]: r for r in st.read(book, "align_ref", key, "align_ref").model_dump()["chars"]}
        ocr_ok = any(r.get("topk") for r in oc.values())
        for s in page_slots(st, book, pg):
            if not s.is_text or s.char in (None, "□"):
                continue
            if a.which == "labeled" and s.id not in labels:
                continue
            n_cells += 1
            # 库信号
            g = gm.get(s.id) or {}
            lib = {c: float(v) for c, v in (g.get("candidates") or [])}
            if s.id in v2_cells:                       # 重算、摘自身
                if matcher is None:
                    p = GlyphMatchParams()
                    matcher, _ = load_matcher_from_db(db, edition=p.edition, knn_k=p.knn_k, norm_stroke=NS)
                r = raw(s.id)
                if r is not None:
                    alias = [j for j, iid in enumerate(matcher._ids) if iid == s.id]
                    for j in alias:
                        matcher._ids[j] = "v2:" + s.id
                    m = matcher.match(normalize_patch(r, stroke_width=NS), exclude_id="v2:" + s.id)
                    for j in alias:
                        matcher._ids[j] = s.id
                    lib = {c: float(v) for c, v in m.candidates}
                    if m.verdict == "same" and m.char and m.char not in lib:
                        lib[m.char] = float(m.cov)
            ocr: dict[str, float] = {}
            ocr_rank: dict[str, int] = {}
            for i, (c, pr) in enumerate((oc.get(s.id) or {}).get("topk") or []):
                for form, w in traditional_candidates(c):
                    ocr[form] = ocr.get(form, 0.0) + float(pr) * w
                    ocr_rank.setdefault(form, i + 1)
            rare: dict[str, float] = {}
            for x in (rc.get(s.id) or {}).get("candidates") or []:
                rare[x["char"]] = max(rare.get(x["char"], 0.0), float(x["score"]))
            ar = al.get(s.id) or {}
            ref, op = ar.get("align_char"), ar.get("align_op")
            lib_sorted = sorted(lib.items(), key=lambda t: -t[1])
            cands = list(dict.fromkeys(
                [c for c, _ in lib_sorted[:5]]
                + [c for c, _ in sorted(ocr.items(), key=lambda t: -t[1])[:5]]
                + [c for c, _ in sorted(rare.items(), key=lambda t: -t[1])[:3]]
                + ([ref] if ref else [])))
            truth = labels.get(s.id)
            if truth is not None and truth not in cands:
                n_uncovered += 1
            # 小笔画判别器：库前两名异字都有人裁实例时
            dd: dict[str, float] = {}
            if len(lib_sorted) >= 2 and lib_sorted[1][1] >= 0.90:
                for c, _ in lib_sorted[:3]:
                    v = disc(s.id, c)
                    if v is not None:
                        dd[c] = v
            for c in cands:
                others_lib = [v for x, v in lib.items() if x != c]
                others_d = [v for x, v in dd.items() if x != c]
                hn = len([e for e in human_ids.get(c, []) if e != s.id])
                row = {
                    "id": s.id, "page": pg, "cand": c, "cur": s.char, "channel": s.channel,
                    "label": None if truth is None else int(c == truth),
                    "lib_cov": lib.get(c, 0.0), "lib_in": int(c in lib),
                    "lib_top1": int(bool(lib_sorted) and lib_sorted[0][0] == c),
                    "lib_margin": lib.get(c, 0.0) - (max(others_lib) if others_lib else 0.0),
                    "lib_top_cov": lib_sorted[0][1] if lib_sorted else 0.0,
                    "human_n": hn, "human_any": int(hn > 0),
                    "ocr_p": ocr.get(c, 0.0), "ocr_rank": ocr_rank.get(c, 9), "ocr_top1": int(ocr_rank.get(c) == 1),
                    "ocr_missing": int(not ocr_ok),
                    "rare_score": rare.get(c, 0.0),
                    "ref_eq": int(ref == c), "ref_sem": int(bool(ref) and ref != c and vm.semantic(ref) == vm.semantic(c)),
                    "ref_none": int(not ref), "ref_op_equal": int(op == "equal"),
                    "confusable": int(bool(partners.get(c, frozenset()) & set(cands))),
                    "disc_d": dd.get(c, -1.0), "disc_has": int(c in dd),
                    "disc_margin": (min(others_d) - dd[c]) if (c in dd and others_d) else 0.0,
                    "n_cands": len(cands),
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                n_rows += 1
        print(f"p{pg} 累计 {n_cells} 格 {n_rows} 行", file=sys.stderr, flush=True)
    out.close()
    print(f"完成：{n_cells} 格、{n_rows} 行；真值不在候选集 {n_uncovered} 格", file=sys.stderr)


if __name__ == "__main__":
    main()
