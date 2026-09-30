# -*- coding: utf-8 -*-
"""字块金标 ↔ 现行 v2 链（cell_shrink）的对接与「人当时看的图块还在不在」判据（M1·A 道，2026-09-30）。

frame-strip / side-rule 的金标是挂在**图块**上的：`(book, page, col, idx)` + 一组由图块算出的
墨量基线。v1 链退役后，`output/<册>/phase4_chars/patches/<页>/<列>_<idx>.png` 不复存在；
v2 链的图块在缓存 `cache/<册>/char_patch/pNNNNcCCsSS.png`，索引在产物
`products/<册>/cell_shrink/pNNNN.json`（`char_index`）。

**能迁的唯一证据**是人当时看的那张图块：数据集 `char-segmentation/instances/patches/
<册>_<页>_<列>_<idx>.png` 存了 909 张人裁过的图块原图（frame-strip 65 条里 18 条、
side-rule 264 条里 12 条有图，且 frame-strip 那 17 条在 instances 里有同一格的人裁
clean/contaminated，与 frame 标注一致）。`same_image()` 拿这张存下来的图块去 v2 图块里做
二值墨的模板匹配（归一化互相关 NCC），**同时**要求最佳位移≤4px、尺寸差≤12px——
三条都过才算「人看的就是这张图」。不拿算法对这一格判了什么当判据（那是循环论证）。

阈值标定（vol01 24 张有图的实测）：NCC 分布是双峰——同图 0.906~0.974，换了切法的 0.23~0.87；
取 0.90。样本小，宁可少留。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_guji_cv.products.kinds  # noqa: E402,F401  注册产物种类
from open_guji_cv.core.spec import page_key  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

NCC_MIN = 0.90
SHIFT_MAX = 4
SIZE_TOL = 12
PAD = 30
#: 人裁图块原图存放处（测试集仓，相对引擎仓 cwd）
SAVED_PATCHES = Path("../open-guji-dataset/char-segmentation/instances/patches")

_st: ProductStore | None = None
_ic: ImageCache | None = None


def _store() -> ProductStore:
    global _st
    if _st is None:
        _st = ProductStore()
    return _st


def _cache() -> ImageCache:
    global _ic
    if _ic is None:
        _ic = ImageCache()
    return _ic


def saved_patch(book: str, page, col, idx) -> np.ndarray | None:
    p = SAVED_PATCHES / f"{book}_{page}_{col}_{idx}.png"
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None


_ensured: set[tuple[str, int]] = set()


def ensure_cells(book: str, page: int) -> str | None:
    """缺 cell_shrink 产物时从原图补跑 Step1→Step4（只补这一页；已有产物不动、不 force）。
    `eval --from-raw` 的 BOOTSTRAP_STEPS 只到 Step3，字块评测还要 Step4。返回失败原因或 None。"""
    if (book, int(page)) in _ensured:
        return None
    _ensured.add((book, int(page)))
    try:
        from open_guji_cv.core.book import load_book
        from open_guji_cv.core.engine import Engine
        from open_guji_cv.core.pipeline import load_pipeline
        from open_guji_cv.utils.bootstrap import BOOTSTRAP_STEPS
        eng = Engine(load_book(book), load_pipeline("keben_body_v2"), store=_store(),
                     cache=_cache(), log=lambda s: None)
        eng.run(steps=list(BOOTSTRAP_STEPS) + ["cell_shrink"], pages=[int(page)])
    except Exception as e:   # noqa: BLE001
        return f"补跑失败 {type(e).__name__}: {str(e)[:100]}"
    return None


def v2_char(book: str, page, col, idx):
    """(v2 图块灰度图或 None, CharRec 或 None, 缺失原因 或 None)。idx = 0 起格号（= CharRec.idx）。"""
    pc = _store().read(book, "cell_shrink", page_key(int(page)), "char_index")
    if pc is None:
        err = ensure_cells(book, int(page))
        pc = _store().read(book, "cell_shrink", page_key(int(page)), "char_index")
        if pc is None:
            return None, None, "v2 产物缺（该页 cell_shrink 没跑/补跑无果" + (f"：{err}" if err else "") + "）"
    c = pc.column(int(col))
    if c is None:
        return None, None, "v2 无此列"
    rs = [x for x in c.chars if x.idx == int(idx) and not x.sub]
    if not rs:
        return None, None, "v2 无此格位"
    r = rs[0]
    if not r.patch_key:
        return None, r, f"v2 该格判为 {r.cell_type}，无图块"
    p = _cache().get(book, "char_patch", r.patch_key)
    if p is None:
        return None, r, "v2 图块缓存缺"
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE), r, None


def same_image(old: np.ndarray, new: np.ndarray) -> dict:
    """{ok, ncc, dx, dy, dh, dw}。old 是人看过的图块，new 是 v2 现图块。"""
    out = dict(ok=False, ncc=None, dx=None, dy=None,
               dh=int(new.shape[0] - old.shape[0]), dw=int(new.shape[1] - old.shape[1]))
    bo = (old < 128).astype(np.float32)
    bn = cv2.copyMakeBorder((new < 128).astype(np.float32), PAD, PAD, PAD, PAD,
                            cv2.BORDER_CONSTANT, value=0)
    if bo.shape[0] > bn.shape[0] or bo.shape[1] > bn.shape[1] or bo.sum() == 0:
        return out
    m = cv2.matchTemplate(bn, bo, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(m)
    out.update(ncc=round(float(mx), 3), dx=int(loc[0] - PAD), dy=int(loc[1] - PAD))
    out["ok"] = bool(mx >= NCC_MIN and abs(out["dx"]) <= SHIFT_MAX and abs(out["dy"]) <= SHIFT_MAX
                     and abs(out["dh"]) <= SIZE_TOL and abs(out["dw"]) <= SIZE_TOL)
    return out


def locate(entry: dict) -> dict:
    """对一条金标：{status, ident?, patch?, rec?, why?}。
    status ∈ scored（图在、可计分）/ no_saved_patch / v2_missing / image_changed。"""
    old = saved_patch(entry["book"], entry["page"], entry["col"], entry["idx"])
    if old is None:
        return dict(status="no_saved_patch",
                    why="没有人当时看的图块原图（instances/patches 里无此格），无从证明图还在")
    new, rec, why = v2_char(entry["book"], entry["page"], entry["col"], entry["idx"])
    if new is None:
        return dict(status="v2_missing", why=why, rec=rec)
    ident = same_image(old, new)
    if not ident["ok"]:
        return dict(status="image_changed", ident=ident,
                    why=f"v2 图块与人看的图块对不上（NCC {ident['ncc']}，位移({ident['dx']},{ident['dy']})，"
                        f"尺寸差({ident['dw']},{ident['dh']})）")
    return dict(status="scored", ident=ident, patch=new, rec=rec)
