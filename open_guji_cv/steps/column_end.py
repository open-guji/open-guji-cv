"""2c 列端字：首、尾紧挨着上下版框的地方，把版框墨抹掉。

五小步拆分（2026-11-25，`doc/2-切字/五小步.md`）从 `column_warp` 里分出来的一步，算法一字未改
（`impl.keben.column.trim_ends` = `column_border_trim` + 双线版框第二道 + 内框线）。2c 排在 2d 字间切分之前
（用户 2026-11-25 定：先切收尾与边框连接处，再切字与字）。输入 2b 界行抹白后的列图 `column_banded`、文字带
`column_bands`，以及 2a 的去噪列图 `column_raw`（e 档边距证据要在抹界行之前的图上算）；输出每列上下端削除档位
`column_ends` 与最终列图 `column_image`（名字沿用，下游照读）。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..impl.keben.column import trim_ends
from ..impl.keben.column_triage import triage_column
from ..products.kinds.columns import BorderTrim, ColumnEndRec, ColumnTriage, PageBands, PageEnds, PageWindows
from ..seg.profile import denoise_column

#: `frame_residue` 判据的三个常数。量的是「清理**之后**上下两端还剩不剩版框墨」，
#: 所以必须在 `cleaned` 上量、在**文字带宽度内**量（带外本来就是界行）。
#:
#: 判据选型是实测定的，另一个候选**被证伪**（bxgb 全书 2052 个端口）：
#: 「端部最大行墨占比」分不开框墨与字墨——削干净的 d/e 档 p50 也有 0.43~0.47，
#: 与漏判的 c 档（0.548）几乎重叠，因为削到框下沿之后紧邻的就是字，
#: 字的横笔一行也能到 0.5~0.7。**别再往峰值这个方向调阈值**。
#:
#: 取的是「满宽连续段」——框线横贯整列宽且连续若干行，字的横笔不满宽也不连续：
#:
#:     档  个数  bar_run p50  p99  ≥3 占比
#:     a   952   0            11   4.6%
#:     b     9   6            10   88.9%
#:     c    26   0             7   3.8%
#:     d   895   0             0   0.0%      ← 正常削干净
#:     e   170   0             0   0.0%      ← 正常削干净
#:
#: d/e 两档 1065 个端口**零误报**（最长段恒为 0），全书命中 53 个端口（a 44 / b 8 / c 1）。
#:
#: 余量只在 d/e 这一侧是干净的（恒 0，离门槛 3 还差 3）。**b 档这一侧没有余量**：
#: 非零值是 [2,4,5,6,6,7,8,9,10]，门槛 3 正落在里面，那个 2 是漏的。
#: 这可以接受——b 档本来就是已知的图像极限（框字粘连成一个连通体，不可剥），
#: 标出来也只是交给人看；真要紧的是别把削干净的列误报成脏，那一侧是零误报。
#: 想往下调到 2 之前先想清楚：a 档的 ≥2 会跟着涨，而 a 档是「贴着边缘削掉几行」，多数本来就干净。
FRAME_RESIDUE_PROBE = 45      # 端部探测深度（约 0.6 格）
FRAME_RESIDUE_COV = 0.85      # 比 clean_column 内部的 0.65 更严：只认「几乎满宽」
FRAME_RESIDUE_MIN_RUN = 3     # 连续多少行才算一条框线


def frame_residue(cleaned: np.ndarray, band: tuple[int, int],
                  probe: int = FRAME_RESIDUE_PROBE,
                  cov: float = FRAME_RESIDUE_COV,
                  ink_threshold: int = 128) -> tuple[int, int]:
    """清理后上/下端各 probe 行内，最长的「满宽连续段」行数。

    返回 `(top_run, bottom_run)`。0 表示这一端没有残留框墨。
    """
    b0, b1 = int(band[0]), int(band[1])
    if b1 <= b0 or cleaned.size == 0:
        return 0, 0
    prof = (cleaned[:, b0:b1] < ink_threshold).mean(axis=1)

    def longest(seg: np.ndarray) -> int:
        best = run = 0
        for v in seg >= cov:
            run = run + 1 if v else 0
            best = max(best, run)
        return int(best)

    return longest(prof[:probe]), longest(prof[-probe:])


class ColumnEndParams(BaseModel):
    ink_threshold: int = 128


def _legacy_band(ctx: RunContext, page: int, col: int) -> tuple[int, int] | None:
    """拆步前的旧产物包（2026-11-25 五小步拆分前，各书钉 0.7.x 线的 main 包）：这一页没有 2b `column_bands`，
    文字带记在 `column_windows` 的 `band` 里（拆分后 2a 不再写这一项）。是旧包就回这一列的旧 `band`，否则 None。

    只在这两样同时成立时认作旧包：新包 2a 不写 `band`，缺 2b 产物的新包仍按原样报「上游产物缺失」。"""
    if ctx.has_product("column_bands", page):
        return None
    rec = ctx.product("column_windows", page).column(col)
    if rec is None or rec.band is None:
        return None
    return int(rec.band[0]), int(rec.band[1])


@register_step
class ColumnEndStep(Step):
    spec = StepSpec(
        id="column_end", title="2c 列端字（上下端抹版框）", version="1.0", unit="column",
        consumes=("column_windows", "column_raw", "column_bands", "column_banded"),
        produces=("column_ends", "column_image"),
        params=ColumnEndParams,
        code_deps=("open_guji_cv.seg.warp", "open_guji_cv.seg.profile", "open_guji_cv.impl.keben.column", "open_guji_cv.impl.keben.border",
                   "open_guji_cv.seg.polyline", "open_guji_cv.seg.frame_types", "open_guji_cv.impl.keben.column_triage"),
        # 双线版框剥第二道读册配置（2026-09-26）——改 yaml 要让列图过期
        book_deps=("frame_layers", "outer_gap"),
    )

    def _one(self, ctx: RunContext, page: int, col: int, p: ColumnEndParams, inner_bottom: float):
        key = column_key(page, col)
        raw = ctx.image("column_raw", key)
        legacy = _legacy_band(ctx, page, col)
        if legacy is None:
            banded = ctx.image("column_banded", key)
            band = ctx.product("column_bands", page).column(col).band
            denoised = denoise_column(raw, ink_threshold=p.ink_threshold)
        else:
            # 旧包重放（CV4 算法待办 #13）：2b 按拆步前的做法在内存里现算，不写包、不进缓存；文字带用包里记的旧值
            band = legacy
            denoised, banded = ctx.producer("column_bands").legacy_strip(ctx, raw)
        fl, og = ctx.book.frame_layers or {}, ctx.book.outer_gap or {}
        out, diag = trim_ends(
            denoised, band, banded, p.ink_threshold,
            layers=(int(fl.get("top", 1)), int(fl.get("bottom", 1))),
            layer_gap=(og.get("top"), og.get("bottom")),
            inner_bottom=inner_bottom)
        return raw, out, diag, band

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnEndParams = ctx.params_for(self)  # type: ignore[assignment]
        wins: PageWindows = ctx.product("column_windows", page)
        recs: list[ColumnEndRec] = []
        for w in wins.columns:
            raw, cleaned, diag, band = self._one(ctx, page, w.col, p, w.border_bottom_in_column)
            ctx.cache.put(ctx.book.id, "column_image", column_key(page, w.col), cleaned)
            res_t, res_b = frame_residue(cleaned, band, ink_threshold=p.ink_threshold)
            recs.append(ColumnEndRec(
                col=w.col,
                trim_top=BorderTrim(px=int(diag["top"]["px"]), case=str(diag["top"]["case"])),
                trim_bottom=BorderTrim(px=int(diag["bottom"]["px"]), case=str(diag["bottom"]["case"])),
                # 在 `cleaned` 上量——判的是「削完之后还剩不剩框墨」，拿 raw 量就成了「削之前有没有框」
                frame_residue_top=res_t, frame_residue_bottom=res_b,
                # 分诊在**清理前**的 `raw` 上做：要判的正是「这一列清得拿不拿得准」，清完再判只能看到清理的结果
                triage=ColumnTriage(**{k: v for k, v in triage_column(raw).items() if k != "band"}),
            ))
        return {"column_ends": PageEnds(page=page, columns=recs)}

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        page, col, _ = parse_key(key)
        if col is None:
            raise ValueError(f"{kind_id} 的键必须带列号: {key}")
        p: ColumnEndParams = ctx.params_for(self)  # type: ignore[assignment]
        wrec = ctx.product("column_windows", page).column(col)
        if wrec is None:
            raise KeyError(f"第 {page} 页没有第 {col} 列")
        return self._one(ctx, page, col, p, wrec.border_bottom_in_column)[1]
