# -*- coding: utf-8 -*-
"""D 铁证复核（2026-09-27 任务书）：把当前 cv main（含 `iron_ref_guard`）跑出来的
`seed_admit` 产物里，全部 `channel="iron"`（真放行）与 `doubts` 含 `iron_vs_ref`
（被拦）的格逐格列出来，每格给：铁证用的是哪个库实例（人裁实例，`iron_evidence`
的证据来源只认人裁）、`align_ref` 的 op 和对齐字、是否被 `iron_vs_ref` 拦下。

只读产物+现算铁证判定的中间量（`_iron_decide` 本身不往外吐 matched_id/second，
这里复用同一份 `iron_evidence` 积木单独算一遍，不改 `seed_admit.py` 的产物结构）。

    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/audit_iron_recheck_0927.py \
        vol03 --pages 1-107 --out /tmp/vol03_iron_recheck.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_guji_cv.clustering.iron_evidence import iron_with_disc  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.seeding import context_conflicts_ref  # noqa: E402
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.utils.image_io import imread  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("--pages", required=True, help="lo-hi")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from open_guji_cv.steps.seed_admit import (SeedAdmitParams, _iron_context,
                                               _iron_page_scale)

    bk = load_book(a.book)
    ns = getattr(bk, "norm_stroke", None)
    p = SeedAdmitParams()
    matcher, human_chars_set, partners_map, human_ids = _iron_context(p.db_path, ns)
    vm = VariantMap.load(p.variants or None)
    st, cache = ProductStore(), ImageCache()
    lo, _, hi = a.pages.partition("-")

    raw_cache: dict[str, object] = {}

    def raw_of(cid: str):
        if cid not in raw_cache:
            bk_, p_, c_, s_ = cid.split(":")
            sub = s_[-1] if s_[-1] in "ab" else ""
            s_ = s_.rstrip("ab")
            pth = cache.get(bk_, "char_patch", f"p{int(p_):04d}c{int(c_):02d}s{s_}{sub}")
            raw_cache[cid] = None if pth is None else imread(str(pth), cv2.IMREAD_GRAYSCALE)
        return raw_cache[cid]

    def ex_raws(ch: str, exclude: str):
        ids = [i for i in human_ids.get(ch, []) if i != exclude]
        return [x for i in ids[:8] if (x := raw_of(i)) is not None]

    rows = []
    n_iron, n_blocked = 0, 0
    for pg in range(int(lo), int(hi or lo) + 1):
        match = st.read(a.book, "glyph_match", f"p{pg:04d}", "glyph_match")
        if match is None:
            continue
        aref = st.read(a.book, "align_ref", f"p{pg:04d}", "align_ref")
        amap = ({c.id: (c.align_char, c.align_op) for c in aref.chars}
               if aref is not None and aref.anchored else {})
        sadm = st.read(a.book, "seed_admit", f"p{pg:04d}", "seed_admit")
        smap = {r.id: r for cc in (sadm.columns if sadm else []) for r in cc.chars}
        scale = _iron_page_scale(a.book, pg, match)
        for cc in match.columns:
            if not cc.ok:
                continue
            for r in cc.chars:
                srec = smap.get(r.id)
                is_iron = srec is not None and srec.channel == "iron"
                is_blocked = srec is not None and "iron_vs_ref" in (srec.doubts or [])
                if not (is_iron or is_blocked):
                    continue
                path = cache.get(a.book, "char_patch", f"p{pg:04d}c{cc.col:02d}s{r.slot}{r.sub or ''}")
                img = imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
                if img is None:
                    rows.append({"id": r.id, "status": "无图块", "channel": srec.channel if srec else None})
                    continue
                res = matcher.match(normalize_patch(img, stroke_width=ns), exclude_id=f"v2:{r.id}")
                cands = [(c, float(v)) for c, v in res.candidates]
                if res.verdict == "same" and res.char and all(c != res.char for c, _ in cands):
                    cands.insert(0, (res.char, float(res.cov)))
                cands.sort(key=lambda t: -t[1])
                winner, top, second, why, disc = iron_with_disc(
                    cands, human_chars_set, partners_map, img,
                    lambda ch: ex_raws(ch, f"v2:{r.id}"), scale)
                align_char, align_op = amap.get(r.id, (None, None))
                matched_id = res.matched_id if res.verdict == "same" else (
                    human_ids.get(winner, [None])[0] if winner else None)
                rows.append({
                    "id": r.id, "iron_char": winner, "cov": round(top, 4),
                    "second": round(second, 4), "why": why, "disc": disc,
                    "matched_instance": matched_id, "label_status": "human" if matched_id else None,
                    "align_char": align_char, "align_op": align_op,
                    "blocked_by_iron_vs_ref": bool(
                        winner and context_conflicts_ref(winner, align_char, vm)),
                    "final_channel": srec.channel if srec else None,
                    "final_char": srec.char if srec else None,
                    "final_admit": bool(srec.admit) if srec else None,
                    "doubts": list(srec.doubts) if srec else None,
                })
                if is_iron:
                    n_iron += 1
                if is_blocked:
                    n_blocked += 1
    Path(a.out).write_text(json.dumps({
        "book": a.book, "pages": a.pages, "n_iron_admitted": n_iron,
        "n_blocked_by_guard": n_blocked, "rows": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.book}: iron 放行 {n_iron} 格，iron_vs_ref 拦下 {n_blocked} 格 → {a.out}")


if __name__ == "__main__":
    main()
