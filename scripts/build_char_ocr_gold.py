# -*- coding: utf-8 -*-
"""建 `char-ocr` 金标分片：单字 OCR 的验收集（换引擎时的尺子）。

    python scripts/build_char_ocr_gold.py [--book vol01] [--pages 4-56,60,70,137,141,151] [--dry-run]

step5_step6_benchmark.md §3.2 缺口 2 说这集"零成本可补"：dev_set 的整理本自动金标 + 字块
就是它。这里把它真的建出来，一格一条（与 rare-char / char-segmentation 分片同一布局）：

- ``anchor``：book / page / col / slot；
- ``input``：字块绝对路径与 patch_key（Step4 的 `char_patch` 缓存）、**冻结的** OCR top-k
  与引擎名（评测时可先在冻结候选上比，再在实时候选上比——step5_step6_benchmark §4 第 2 条）；
- ``expected``：``char`` = 刻本字形（人裁优先，其次 v2 对齐金标的 shape）、``reading`` = 整理本字、
  ``is_variant`` = 两者不同、``align_opcode`` = equal | replace（**分层读**，equal 段是自证）、
  ``label_origin`` = human | align、``corpus_freq``。

OCR 的 KPI 是**候选召回@k** 与**字表不可达率**，不是 top1（§2.2）；``is_variant`` 子集单独报，
因为字典偏通行字的引擎在异体位天然吃亏——这正是换引擎最该盯的那一层。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import cell_key, page_key  # noqa: E402
from open_guji_cv.eval.round_check import load_verdicts  # noqa: E402
from open_guji_cv.gold.item import Anchor, GoldItem  # noqa: E402
from open_guji_cv.gold.store import GoldStore  # noqa: E402
from open_guji_cv.gold.v2_align import align_book  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.variant_ledger import han_counter  # noqa: E402

SHARD = "char-ocr"
DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--pages", default="4-56,60,70,137,141,151")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    st = ProductStore()
    bk = load_book(a.book)
    pages = bk.resolve_pages(a.pages)
    dev = set(bk.dev_set)
    truth = load_verdicts(a.book)
    cp = REPO / a.corpus
    ref = han_counter(cp.read_text(encoding="utf-8")) if cp.exists() else Counter()
    cache = ImageCache()

    items: list[GoldItem] = []
    stats = Counter()
    for g in align_book(a.book, pages, st):
        if not g.anchored:
            stats["page_unanchored"] += 1
            continue
        ocr = st.read(a.book, "ocr_candidates", page_key(g.page), "ocr_candidates")
        omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}
        for c in g.chars:
            sub = c.id[-1] if c.id and c.id[-1] in "ab" else ""
            key = cell_key(g.page, c.col, c.slot) + sub
            patch = cache.path(a.book, "char_patch", key)
            if not patch.exists():
                stats["no_patch"] += 1
                continue
            human = truth.get(c.id)
            shape = human or c.shape
            if not shape:
                stats["no_shape"] += 1
                continue
            o = omap.get(c.id)
            items.append(GoldItem(
                id=c.id,
                anchor=Anchor(book=a.book, page=g.page, col=c.col, slot=c.slot),
                input={"patch": str(patch), "patch_key": key,
                       "ocr_topk": [list(t) for t in (o.topk[:10] if o else [])],
                       "ocr_engine": (o.engine if o else "") or (ocr.engine if ocr else "")},
                expected={"char": shape, "reading": c.reading or shape,
                          "is_variant": bool(shape != (c.reading or shape)),
                          "align_opcode": c.align_op,
                          "label_origin": "human" if human else "align",
                          "corpus_freq": int(ref.get(shape, 0))},
                label_origin="human" if human else "align",
                stratum="dev_set" if g.page in dev else "body",
            ))
            stats["items"] += 1
            stats[f"origin:{'human' if human else 'align'}"] += 1
            stats[f"opcode:{c.align_op}"] += 1
            stats["variant"] += bool(shape != (c.reading or shape))
    print(f"char-ocr：{stats['items']} 条  " + "  ".join(f"{k}={v}" for k, v in sorted(stats.items()) if k != "items"))
    if a.dry_run:
        return 0
    gs = GoldStore()
    added, updated = gs.upsert(SHARD, items, why="build_char_ocr_gold：v2 对齐金标 + 人裁 + 冻结 OCR 候选")
    n_ret = gs.retire(SHARD, ["000-example"], why="占位骨架，真实条目已入")
    print(f"写入 {SHARD}：新增 {added}，更新 {updated}，退役占位 {n_ret}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
