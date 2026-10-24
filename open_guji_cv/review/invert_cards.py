# -*- coding: utf-8 -*-
"""反色带候选的审卡（Step0，2026-10-22）。

`steps/invert_detect.py` 自动找疑似反色带，**不自动修**——粗外框与窄反色带分不干净（Sheldon 10-22 定
「自动认＋送审，人点头才修」）。一页一张卡：候选黑条、建议修法、修前修后两张图。人点「是」落一条
`inverted_band` 事件（payload: verdict, rules），`utils.preclean.effective_raw_path` 之后就读修好的图，
各步按原图 sha 变了自然判过期；点「否」的页不再出卡（仍可在「已审」里看到、改判）。

书 yaml `preclean:` 已登记的页不出卡：那些页读的是修好的图，`invert_detect` 本来就不会再报。
卡片 id `invert:{book}:{page}`（`feedback/keys._ID_PATTERNS` 的 prefix:book:page 形）。
"""
from __future__ import annotations

import numpy as np

from ..core.book import load_book
from ..core.spec import page_key
from ..feedback.lookup import resolved_inverted
from ..products.kinds import inverted as _inverted  # noqa: F401  —— 登记 inverted 产物种类
from ..products.store import ProductStore
from ..utils.preclean import apply_preclean, rule_mask

QUESTION = "invert_detect.page.is_inverted"
CROP_PAD = 400      # 预览图在候选黑条上下各多露多少行（要看得出是版框还是正文里的一条带）
PREVIEW_SCALE = 0.5


def _bands(store: ProductStore, book: str, page: int):
    d = store.read(book, "invert_detect", page_key(page), "inverted")
    return list(d.bands) if d else []


def _rule_mask(gray: np.ndarray, r: dict) -> np.ndarray | None:
    try:
        return rule_mask(gray, r)
    except (KeyError, ValueError):
        return None


def cards(store: ProductStore, book: str, pages: list[int] | None = None, *, include_decided: bool = False) -> list[dict]:
    """本书（或点名页）有候选、没在 yaml 登记过的页。缺省只出没审过的和点了「是」的（点「否」的不再出）。"""
    bk = load_book(book)
    decided = resolved_inverted(book)
    out = []
    for page in (pages if pages is not None else bk.resolve_pages("all")):
        if page in (bk.preclean or {}):
            continue
        bands = _bands(store, book, page)
        v = decided.get(page)
        if not bands and not (v and include_decided):
            continue
        if v and v["verdict"] == "no" and not include_decided:
            continue
        rules = v["rules"] if v and v.get("rules") else [b.rule for b in bands]
        out.append({"id": f"invert:{book}:{page}", "page": page, "question": QUESTION,
                    "bands": [b.model_dump() for b in bands], "rules": rules,
                    "verdict": v["verdict"] if v else None})
    return out


def preview(book: str, page: int, rules: list[dict], which: str) -> np.ndarray:
    """修前（`which="before"`）或照 `rules` 修后的预览图：候选附近一条通栏，缩到一半。"""
    import cv2

    from ..utils.image_io import imread
    bk = load_book(book)
    gray = imread(str(bk.raw_path(page)), cv2.IMREAD_GRAYSCALE)   # 卡上比的是原图与照规则修的图，不经 effective_raw_path
    ys = []
    for r in rules:
        m = _rule_mask(gray, r)
        if m is not None and m.any():
            rows = np.flatnonzero(m.any(1))
            ys += [int(rows[0]), int(rows[-1])]
    img = apply_preclean(gray, rules, gate=False)[0] if which == "after" else gray
    if ys:
        img = img[max(0, min(ys) - CROP_PAD):min(gray.shape[0], max(ys) + CROP_PAD)]
    return cv2.resize(img, None, fx=PREVIEW_SCALE, fy=PREVIEW_SCALE, interpolation=cv2.INTER_AREA)
