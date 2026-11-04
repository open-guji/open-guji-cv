"""切坏格检测（第一期：只读、只标，2026-11-04，史記第 8 轮计划第 3 项；A22、A31 评审过）。

离线工具，**不是 Step、不进任何 Step 的 code_deps**，不改放行。读一册若干页的 row_segment／cell_shrink／
seed_admit／align_ref 产物与字块缓存，把疑似切坏的格列成表，人看抽样后再定第二期的闸
（第二期在 seed_admit 写 `evidence.seg_kind`，why 码仍是 `seg_defect`，见 `review/reasons.py` 的 `SEG_KINDS`）。

四种 `seg_kind`（设计稿 ai-team domain/CV/质检/史記-r8-交A22/切坏检测判法设计稿-SJ.md）：

- `merged`  两字并一格：墨高 ≥ `MERGED_H` 倍基准（整字格按格高 `period`，夹注半格按本列夹注半格墨高中位），
  且竖向投影中段有低谷（墨 < `MERGED_VALLEY` 峰值、长 ≥ `MERGED_GAP` 格高），低谷上下两团各高 ≥ `MERGED_PART` 格高
  （防「三」「二」这种字中间本来就有空行）。
- `clipped` 字被切掉一截：Step3 选中的切线穿墨（`cut_candidates` 里选中那条的 `seam_ink` ≥ `CLIP_SEAM_INK`），
  线两侧的格都标；或 cell_shrink 已打 `boundary_ink` 旗（A22：05:15:8:1a 字头被切到格外）。
- `bleed`   邻格笔画溢入：cell_shrink 的 `edge_blob` 旗（上下带里与主体隔开的一块墨，`extractor._shape_features`）。
  A22 建议改用 `partition_strip` 的归属图，第一期先用现成旗，抽样不准再换。
- `frame_residue` 框线残笔：列首／列尾格（贴着版框一格高以内）的最终字块上，按全页半格线位
  （`CellShrinkStep._page_frame_lines` 同一算法，夹注半格线位）用 `extractor.inner_frame_band_mask` 还认得出线的
  （与 cell_shrink 剥线同一个定义；剥过还在＝没剥干净）。夹注 a/b 各自一块图块，各判。

用法：`python -m open_guji_cv.review.seg_defect <册> --pages 2,10 -w <工作区> [--out x.tsv]`；不给 --pages 跑整册。
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

import numpy as np

SEG_KINDS = ("merged", "clipped", "bleed", "frame_residue")

MERGED_H = 1.6
MERGED_VALLEY = 0.10
MERGED_GAP = 0.08
MERGED_PART = 0.30
CLIP_SEAM_INK = 12

FIELDS = ("格号", "seg_kind", "特征", "放行", "通道", "机器字", "整理本字", "字块键")


def _valley_split(patch: np.ndarray, cell_h: float) -> str | None:
    """竖向投影中段的低谷：返回特征说明，没有就 None。"""
    if patch is None or patch.size == 0:
        return None
    ink = (patch < 128).sum(axis=1).astype(float)
    if ink.max() <= 0:
        return None
    nz = np.nonzero(ink)[0]
    top, bot = int(nz[0]), int(nz[-1])
    low = ink < MERGED_VALLEY * ink.max()
    best = None
    y = top
    while y <= bot:
        if low[y]:
            y0 = y
            while y <= bot and low[y]:
                y += 1
            if y0 > top and y <= bot and (y - y0) >= MERGED_GAP * cell_h \
                    and (y0 - top) >= MERGED_PART * cell_h and (bot - y + 1) >= MERGED_PART * cell_h:
                best = (y0, y)
        y += 1
    return None if best is None else f"valley={best[0]}-{best[1]}"


def _patch(cache, book: str, key: str | None):
    if not key:
        return None
    import cv2
    p = cache.path(book, "char_patch", key)
    if not p.exists():
        return None
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)


class _LineCtx:
    """给 `CellShrinkStep._page_frame_lines` 用的最小上下文：只读列图、参数取 cell_shrink 缺省＋半格线位开。"""

    def __init__(self, cache, book: str, frame_line_max_off: float):
        from ..steps.cell_shrink import CellShrinkParams
        self._cache, self._book = cache, book
        self._p = CellShrinkParams(frame_line_max_off=frame_line_max_off, jiazhu_strip_rules=True)

    def image(self, kind: str, key: str):
        import cv2
        return cv2.imread(str(self._cache.path(self._book, kind, key)), cv2.IMREAD_GRAYSCALE)

    def params_for(self, _step):
        return self._p


def _frame_residue(patch, r, cc_cells, lines: dict) -> str | None:
    """列端格最终字块上还认得出的内框细线：返回特征说明，没有就 None。"""
    from ..clustering.extractor import inner_frame_band_mask
    if patch is None or cc_cells is None:
        return None
    cell_h = float(cc_cells.period or 0)
    if cell_h <= 0:
        return None
    x0, y0 = r.bbox_col[0], r.bbox_col[1]
    out = []
    for bottom, key, edge in ((False, "frame_half_lines_top", cc_cells.border_top),
                              (True, "frame_half_lines_bottom", cc_cells.border_bottom)):
        lys = (lines.get(key) or {}).get(cc_cells.col) or []
        if edge is None or not lys:
            continue
        near = (r.bbox_col[3] >= edge - cell_h) if bottom else (r.bbox_col[1] <= edge + cell_h)
        if not near:
            continue
        ly = tuple((float(v) - y0, float(th)) for v, th in lys)
        m = inner_frame_band_mask(np.ascontiguousarray(patch), cell_h, bottom, ly)
        if m is not None and m.any():
            out.append(("下" if bottom else "上") + f"线 {int(m.sum())}px")
    return " ".join(out) or None


def scan_page(book: str, page: int, store, cache, frame_line_max_off: float = 0.35) -> list[dict]:
    from .. import steps  # noqa: F401  —— 注册产物种类
    from ..core.spec import page_key
    from ..products.alt_view import read_view, resolve_patch_key
    pk = page_key(page)
    cells = read_view(store, book, "row_segment", pk, "cells")
    chars = read_view(store, book, "cell_shrink", pk, "char_index")
    adm = store.read(book, "seed_admit", pk, "seed_admit")
    ref = store.read(book, "align_ref", pk, "align_ref")
    if chars is None:
        return []
    arec = {r.id: r for c in (adm.columns if adm else []) for r in c.chars}
    coord = {r.id: r.ref_char for r in (ref.coord if ref else [])}
    # Step3 切线穿墨：(列, 格号) → seam_ink
    seam: dict[tuple[int, int], int] = {}
    period: dict[int, float] = {}
    for cc in (cells.columns if cells else []):
        period[cc.col] = float(cc.period or 0) or 0.0
        for cut in (getattr(cc, "cut_candidates", None) or []):
            cut = cut if isinstance(cut, dict) else cut.model_dump()
            cands, i = cut.get("candidates") or [], cut.get("chosen") or 0
            if not cands or i >= len(cands):
                continue
            si = int(cands[i].get("seam_ink") or 0)
            if si >= CLIP_SEAM_INK:
                for s in (cut.get("slot_above"), cut.get("slot_below")):
                    if s is not None:
                        seam[(cc.col, int(s))] = max(seam.get((cc.col, int(s)), 0), si)
    lines: dict = {}
    if cells is not None:
        from ..steps.cell_shrink import CellShrinkStep
        try:
            lines = CellShrinkStep._page_frame_lines(None, _LineCtx(cache, book, frame_line_max_off), page, cells)
        except Exception:                      # noqa: BLE001 —— 缺列图就不判这一类
            lines = {}
    by_col = {cc.col: cc for cc in (cells.columns if cells else [])}
    out: list[dict] = []
    for cc in chars.columns:
        jz = [r.height for r in cc.chars if r.sub and r.patch_key and r.height]
        jz_med = statistics.median(jz) if jz else 0.0
        ph = period.get(cc.col) or 0.0
        for r in cc.chars:
            if not r.patch_key or r.cell_type == "empty":
                continue
            hits: list[tuple[str, str]] = []
            base = jz_med if r.sub else ph
            if base and r.height >= MERGED_H * base:
                v = _valley_split(_patch(cache, book, resolve_patch_key(book, r.patch_key, store)), base)
                if v:
                    hits.append(("merged", f"h={r.height:.0f}/{base:.0f} {v}"))
            si = seam.get((cc.col, r.slot))
            if si:
                hits.append(("clipped", f"seam_ink={si}"))
            elif "boundary_ink" in r.flags:
                hits.append(("clipped", "boundary_ink"))
            if "edge_blob" in r.flags:
                hits.append(("bleed", "edge_blob"))
            if lines:
                fr = _frame_residue(_patch(cache, book, resolve_patch_key(book, r.patch_key, store)),
                                    r, by_col.get(cc.col), lines)
                if fr:
                    hits.append(("frame_residue", fr))
            a = arec.get(r.id)
            for kind, feat in hits:
                out.append({"格号": r.id.split(":", 1)[1] if r.id.count(":") >= 4 else r.id,
                            "seg_kind": kind, "特征": feat,
                            "放行": "是" if a is not None and a.admit else "否",
                            "通道": (a.channel or "") if a is not None else "",
                            "机器字": (a.char or "") if a is not None else "",
                            "整理本字": coord.get(r.id) or "",
                            "字块键": r.patch_key})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("--pages", default="")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--frame-line-max-off", type=float, default=0.35, help="同册配置 cell_shrink.frame_line_max_off")
    a = ap.parse_args(argv)
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    ws = Path(a.workspace)
    store, cache = ProductStore(ws / "products"), ImageCache(ws / "cache")
    if a.pages:
        pages = [int(x) for x in a.pages.split(",") if x.strip()]
    else:
        pages = sorted(int(p.stem[1:]) for p in store.step_dir(a.book, "cell_shrink").glob("p*.json"))
    rows = [r for p in pages for r in scan_page(a.book, p, store, cache, a.frame_line_max_off)]
    f = open(a.out, "w", encoding="utf-8", newline="") if a.out else sys.stdout
    w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t")
    w.writeheader()
    w.writerows(rows)
    if a.out:
        f.close()
    by = {k: sum(1 for r in rows if r["seg_kind"] == k) for k in SEG_KINDS}
    print(f"{a.book}: {len(pages)} 页，{len(rows)} 条 {by}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
