# -*- coding: utf-8 -*-
"""column-warp 金标 ↔ 现行 v2 链（keben_body_v2 / column_warp Step）的对接层（M1·A 道，2026-09-30）。

旧口径读 `output/<册>/step2_columns/…png`（`regen_step2_columns.py` 预导的列图，
v1 时代的落点，云端没有）；v2 链的列图在 **缓存** `cache/<册>/column_raw/pNNNNcNN.png`，
文字带 / 版框削行类别在**产物** `products/<册>/column_warp/pNNNN.json` 的 `column_windows`。
这里负责：

1. `load_v2(book, page, col)`  取 v2 的 (矫正+去噪列图, 产物里的 ColumnWindowRec)；
2. `identity(sample, raw)`     **这条人裁当时看的那张图，现在还在不在**——金标能不能继续用的唯一判据。

## 判据：只看「图」，不看算法答案（绝不循环论证）

一条文字带人裁对**它当时看的那张列图**成立，人看的是整列图 + 沿竖直方向的投影曲线，
拖的是两个 x。图像同一性分三档（任一成立即留用，记下走的是哪档）：

| 档 | 判据 | 说明 |
|---|---|---|
| `fingerprint` | 整列图指纹 `column_fingerprint` 平均绝对差 ≤ 6 灰阶 | 与 `migrate_column_warp_gold.py` 相同，图像整体没变 |
| `profile` | 宽度差 ≤ 2px 且 **投影曲线**（样本里存的 `profile`，即人当时看的那条曲线）与现图同一 x 上的平均绝对差 ≤ 0.012 | v2 窗口比旧窗口**纵向多了约 50~70px**（`bottom_pad=40` 等），整图指纹因此整体漂移（实测 57 条 vol01 里只有 7 条 ≤6），但人裁的 x 坐标只取决于横向结构——曲线没变就等于「人看的横向证据还在」 |
| `remedy_clean` | 仅 `clean` 列；宽度差 ≤ 3px；`human_left/right` 落在新图上，墨占比仍 ≤ 0.01（金标自己的定义）| 与旧脚本同一补救通道；`canonical_*` 按新图重推。**不适用 mixed/idk**（它们本来就没有零墨边界）|

`profile` 档阈值 0.012 的标定（vol01 57 条）：指纹档留用的列曲线 MAD 0.002~0.0097；
宽度差 ≥10px 的列（窗口/边线真的变了）MAD ≥0.0235；取两者之间的 0.012。
样本量小，阈值偏保守，宁可少留。
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_guji_cv.products.kinds  # noqa: E402,F401  注册产物种类
from open_guji_cv.core.spec import column_key, page_key  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.utils.column_projection import column_profile  # noqa: E402

FP_TOL = 6.0
COL_FP_SIZE = (24, 96)
PROF_TOL = 0.012
PROF_DW = 2
REMEDY_DW = 3
KEEP_EPS = 0.01
ZERO_EPS = 0.005

_store: ProductStore | None = None
_cache: ImageCache | None = None


def _s() -> ProductStore:
    global _store
    if _store is None:
        _store = ProductStore()
    return _store


def _c() -> ImageCache:
    global _cache
    if _cache is None:
        _cache = ImageCache()
    return _cache


_ensured: set[tuple[str, int]] = set()


def ensure_page(book: str, page: int) -> None:
    """缺 column_warp 产物时从原图补跑 Step1→Step3（与 `eval --from-raw` 同一组步骤，只补这一页，不 force）。"""
    if (book, int(page)) in _ensured:
        return
    _ensured.add((book, int(page)))
    try:
        from open_guji_cv.core.book import load_book
        from open_guji_cv.core.engine import Engine
        from open_guji_cv.core.pipeline import load_pipeline
        from open_guji_cv.utils.bootstrap import BOOTSTRAP_STEPS
        eng = Engine(load_book(book), load_pipeline("keben_body_v2"), store=_s(),
                     cache=_c(), log=lambda s: None)
        eng.run(steps=list(BOOTSTRAP_STEPS), pages=[int(page)])
    except Exception:   # noqa: BLE001  册没定义/原图缺：交给调用方按「产物缺」报
        pass


def load_v2(book: str, page: int, col: int, ensure: bool = True):
    """(column_raw 灰度图, ColumnWindowRec)；缺产物或缺列图返回 None（默认先试着从原图补这一页）。"""
    pw = _s().read(book, "column_warp", page_key(int(page)), "column_windows")
    if pw is None and ensure:
        ensure_page(book, page)
        pw = _s().read(book, "column_warp", page_key(int(page)), "column_windows")
    if pw is None:
        return None
    rec = pw.column(int(col))
    if rec is None:
        return None
    p = _c().get(book, "column_raw", column_key(int(page), int(col)))
    if p is None:
        return None
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return img, rec


def fp_diff(stored: str, img: np.ndarray, size=COL_FP_SIZE) -> float:
    a = np.frombuffer(base64.b64decode(stored), dtype=np.uint8).reshape(size[1], size[0])
    b = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return float(np.abs(a.astype(int) - b.astype(int)).mean())


def profile_mad(gold_prof: list[float], raw: np.ndarray) -> tuple[float, int]:
    """金标存的投影曲线 vs 现图同 x 的曲线：(平均绝对差, 宽度差=现图宽-金标宽)。
    只比公共宽度，不做平移对齐（平移过的视为图变了，不猜）。"""
    g = np.asarray(gold_prof, dtype=float)
    p = column_profile(raw)
    n = min(len(g), len(p))
    return float(np.abs(g[:n] - p[:n]).mean()), int(len(p) - len(g))


def identity(sample: dict, raw: np.ndarray) -> dict:
    """返回 {ok, channel, fp, prof_mad, dw, canonical?}。channel ∈ fingerprint/profile/remedy_clean/None。"""
    out = dict(ok=False, channel=None, fp=None, prof_mad=None, dw=None)
    fp = sample.get("column_fingerprint")
    if fp:
        out["fp"] = round(fp_diff(fp, raw), 1)
    if sample.get("profile"):
        mad, dw = profile_mad(sample["profile"], raw)
        out["prof_mad"], out["dw"] = round(mad, 4), dw
    if out["fp"] is not None and out["fp"] <= FP_TOL and (out["dw"] is None or abs(out["dw"]) <= REMEDY_DW):
        return {**out, "ok": True, "channel": "fingerprint"}
    if out["prof_mad"] is not None and abs(out["dw"]) <= PROF_DW and out["prof_mad"] <= PROF_TOL:
        return {**out, "ok": True, "channel": "profile"}
    tb = sample.get("text_band") or {}
    if sample.get("verdict") == "clean" and tb and out["dw"] is not None and abs(out["dw"]) <= REMEDY_DW:
        prof = column_profile(raw)
        hl, hr = tb["human_left"], tb["human_right"]
        if hl < len(prof) and 0 < hr <= len(prof):
            ink = max(float(prof[hl]), float(prof[hr - 1]))
            if ink <= KEEP_EPS:
                cl, cr = hl, hr
                while cl - 1 >= 0 and prof[cl - 1] <= ZERO_EPS:
                    cl -= 1
                while cr < len(prof) and prof[cr] <= ZERO_EPS:
                    cr += 1
                return {**out, "ok": True, "channel": "remedy_clean",
                        "canonical": [cl, cr], "ink_at_human": round(ink, 4)}
    return out
