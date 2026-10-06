"""诊断脚本（D 道，任务书 D-align_ref锚定召回-全唐文）：给全唐文 v006 逐页分类
「套语碰撞」vs「8 连字全对太难」两种锚不住的成因。

不改产线代码，只读 align_ref 已有产物 + 复算一些 anchor_page_diag 内部量
（避免为了诊断去改 align_eval.py 的返回结构）。

用法：
    .venv/bin/python research/align_anchor_recall/diagnose_v006.py \
        -w <sandbox workspace> --book v006 --out <out.json>
"""
from __future__ import annotations

import argparse
import difflib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from open_guji_cv.clustering.align_eval import (  # noqa: E402
    GRAM, POOL_RADIUS, WINDOW_PAD, build_ngram_index,
)
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import page_key  # noqa: E402
from open_guji_cv.core.workspace import corpus_path  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.steps.align_ref import slots_from_evidence  # noqa: E402


def raw_peak_diag(text: str, index: dict, gram: int = GRAM) -> dict:
    """复算 anchor_page_diag 的投票内部量，但不套用 MIN_VOTES/占比/优势三条闸——
    诊断用，要看闸拦住之前的原始票况，不是锚定成不成。"""
    n_grams = len(text) - gram + 1
    if n_grams <= 0:
        return {"n_grams": 0, "n_hit_grams": 0, "avg_hits_per_hit_gram": 0.0,
                "peak_offset": None, "peak_votes": 0, "n_clusters": 0,
                "runner_up_votes": 0}
    votes: Counter[int] = Counter()
    hit_grams = 0
    hit_sizes = []
    for i in range(n_grams):
        g = text[i:i + gram]
        hits = index.get(g, ())
        if hits:
            hit_grams += 1
            hit_sizes.append(len(hits))
        for pos in hits:
            votes[pos - i] += 1
    if not votes:
        return {"n_grams": n_grams, "n_hit_grams": 0, "avg_hits_per_hit_gram": 0.0,
                "peak_offset": None, "peak_votes": 0, "n_clusters": 0,
                "runner_up_votes": 0}
    peak = votes.most_common(1)[0][0]
    near = [o for o in votes if abs(o - peak) <= POOL_RADIUS]
    peak_votes = sum(votes[o] for o in near)
    rest = {o: v for o, v in votes.items() if abs(o - peak) > POOL_RADIUS}
    runner_up = 0
    if rest:
        peak2 = max(rest, key=rest.get)
        runner_up = sum(v for o, v in rest.items() if abs(o - peak2) <= POOL_RADIUS)
    # 粗略数一下有多少个「独立簇」（供围观分散程度，不追求精确）
    remaining = dict(votes)
    n_clusters = 0
    while remaining:
        top = max(remaining, key=remaining.get)
        n_clusters += 1
        remaining = {o: v for o, v in remaining.items() if abs(o - top) > POOL_RADIUS}
    return {
        "n_grams": n_grams,
        "n_hit_grams": hit_grams,
        "avg_hits_per_hit_gram": round(statistics.mean(hit_sizes), 2) if hit_sizes else 0.0,
        "peak_offset": min(near),
        "peak_votes": peak_votes,
        "n_clusters": n_clusters,
        "runner_up_votes": runner_up,
    }


def best_effort_error_rate(text: str, corpus: str, offset: int | None,
                            window_pad: int = WINDOW_PAD) -> dict:
    """在（可能达不到锚定门槛的）候选偏移上做一次 difflib 比对，估计刻本侧
    字串在这个候选窗口上的「错字率」——仅供参考，偏移本身可能是错的。"""
    if offset is None:
        return {"offset_used": None, "equal_frac": None, "replace_frac": None}
    lo = max(0, offset)
    hi = min(len(corpus), offset + len(text) + window_pad)
    window = corpus[lo:hi]
    sm = difflib.SequenceMatcher(None, text, window, autojunk=False)
    equal = sum(b.size for b in sm.get_matching_blocks())
    total = len(text)
    return {
        "offset_used": offset,
        "equal_frac": round(equal / total, 4) if total else None,
        "replace_frac": round(1 - equal / total, 4) if total else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--book", default="v006")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from open_guji_cv.core import workspace as ws_mod
    ws_mod.set_workspace_override(str(Path(args.workspace).resolve()))

    book = load_book(args.book)
    refs = book.references
    corpus_file = corpus_path(refs[0]["file"]) if refs and refs[0].get("file") \
        else corpus_path("zongmu_wenyuange_wikisource.txt")
    corpus_text_raw = Path(corpus_file).read_text(encoding="utf-8")
    import re
    non_han = re.compile(r"[^一-鿿]")
    corpus_text = non_han.sub("", corpus_text_raw)
    index = build_ngram_index(corpus_text)

    store = ProductStore()
    pages = book.all_pages()
    rows = []
    for pg in pages:
        match = None
        try:
            match = store.read(args.book, "glyph_match", page_key(pg), "glyph_match")
        except Exception:
            pass
        ocr = None
        try:
            ocr = store.read(args.book, "ocr_candidates", page_key(pg), "ocr_candidates")
        except Exception:
            pass
        ar = None
        try:
            ar = store.read(args.book, "align_ref", page_key(pg), "align_ref")
        except Exception:
            pass

        if match is None and ocr is None:
            rows.append({"page": pg, "status": "no_evidence"})
            continue

        slots = slots_from_evidence(match, ocr)
        text = "".join(s[-1] for s in slots)
        diag = raw_peak_diag(text, index)
        err = best_effort_error_rate(text, corpus_text, diag["peak_offset"])

        rows.append({
            "page": pg,
            "anchored": bool(ar and ar.anchored),
            "note": ar.note if ar else None,
            "n_slots": len(slots),
            **diag,
            **err,
        })

    n_anchored = sum(1 for r in rows if r.get("anchored"))
    summary = {
        "book": args.book,
        "n_pages": len(rows),
        "n_anchored": n_anchored,
        "n_not_anchored": len(rows) - n_anchored,
        "pages": rows,
    }
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"{args.book}: {n_anchored}/{len(rows)} anchored; 写入 {args.out}")


if __name__ == "__main__":
    main()
