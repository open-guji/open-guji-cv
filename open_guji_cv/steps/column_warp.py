"""Step2 单列射影变换 + 去噪 + 界行 / 版框清除。

包的是 `utils/column_projection` 的 page_column_windows → warp_column → denoise_column →
clean_column。numeric 产物存复现所需的全部量；两种列图（矫正去噪 / 清理后）只进缓存，
`render` 用同一条路径现算——射影与清理都是 (原图, Step1 线, 参数, 代码版本) 的确定性函数。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.borders import Borders, VLineRec
from ..products.kinds.columns import BorderTrim, ColumnTriage, ColumnWindowRec, PageWindows
from ..utils.column_triage import triage_column
from ..utils.column_projection import (ColumnWindow, clean_column, column_profile,
                                       denoise_column, page_column_windows,
                                       stamp_noise_density, warp_column)


class ColumnWarpParams(BaseModel):
    body_pad: float = 0.0
    bottom_pad: float = 40.0          # 下界额外开的余量，见 column_projection.BOTTOM_PAD
    head_pad: float = 30.0            # 抬头列上界在抬头框线心之上再开的余量，见 column_projection.HEAD_PAD
    ink_threshold: int = 128
    min_blob_area: int = 6            # denoise_column
    side_floor_look: float = 0.25     # 交接闸 L2 用：两侧各看进去多少比例的宽度


def side_floor(raw: np.ndarray, look: float = 0.25, ink_threshold: int = 128) -> float:
    """两侧各外 look 里的最低墨占比，取两侧较大者。在**原始矫正图**上量，不是清理后。"""
    prof = column_profile(raw, ink_threshold=ink_threshold)
    k = max(1, int(round(look * len(prof))))
    return max(float(prof[:k].min()), float(prof[-k:].min()))


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
#: d/e 两档 1065 个端口**零误报**（最长段恒为 0），全书命中 53 个端口
#: （a 44 / b 8 / c 1）。
#:
#: 余量只在 d/e 这一侧是干净的（恒 0，离门槛 3 还差 3）。**b 档这一侧没有余量**：
#: 非零值是 [2,4,5,6,6,7,8,9,10]，门槛 3 正落在里面，那个 2 是漏的。
#: 这可以接受——b 档本来就是已知的图像极限（框字粘连成一个连通体，不可剥），
#: 标出来也只是交给人看；真要紧的是别把削干净的列误报成脏，那一侧是零误报。
#: 想往下调到 2 之前先想清楚：a 档的 ≥2 会跟着涨，而 a 档是「贴着边缘削掉几行」，
#: 多数本来就干净。
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


@register_step
class ColumnWarpStep(Step):
    spec = StepSpec(
        id="column_warp", title="Step2 单列射影 + 去噪 + 清理", version="1.4", unit="column",
        consumes=("raw_page", "borders", "border_detect_gate_manifest"),
        produces=("column_windows", "column_raw", "column_image"),
        params=ColumnWarpParams,
        code_deps=("open_guji_cv.utils.column_projection", "open_guji_cv.utils.border_geometry",
                   "open_guji_cv.utils.column_triage"),
    )

    # ── 共用的一列计算 ─────────────────────────────────────────────────
    def _windows(self, ctx: RunContext, page: int) -> tuple[np.ndarray, Borders, list[ColumnWindow]]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        gray = ctx.raw_page(page)
        borders: Borders = ctx.product("borders", page)
        wins = page_column_windows(borders.to_result(), body_pad=p.body_pad,
                                   bottom_pad=p.bottom_pad, head_pad=p.head_pad)
        return gray, borders, wins

    def _images(self, ctx: RunContext, gray: np.ndarray, win: ColumnWindow
                ) -> tuple[np.ndarray, np.ndarray, dict, np.ndarray]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        warped = warp_column(gray, win.left, win.right, win.top_y, win.bottom_y)
        raw = denoise_column(warped, ink_threshold=p.ink_threshold, min_blob_area=p.min_blob_area)
        cleaned, diag = clean_column(raw, ink_threshold=p.ink_threshold)
        return raw, cleaned, diag, warped

    # ── Step 接口 ─────────────────────────────────────────────────────
    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        gate: BorderDetectGateManifest = ctx.product("border_detect_gate_manifest", page)
        if gate.page_type_policy == "skip":
            # 闸1 判定这页没有正文栏格（封面/书签/牌记）——射影/去噪/清理
            # 都是白费功夫（page_type.py 模块头实测：书签页照切会切出 126 个
            # 无意义的块）。产出空列表，闸2 的 L1（探出列数!=版式列数）会自然
            # 拒收，不用在这里重复判一次「该不该拦」。
            gray = ctx.raw_page(page)
            h, w = gray.shape[:2]
            borders: Borders = ctx.product("borders", page)
            return {"column_windows": PageWindows(
                page=page, page_size=(int(w), int(h)),
                vline_segments=int(borders.vline_segments), denoised=True, columns=[])}
        gray, borders, wins = self._windows(ctx, page)
        recs: list[ColumnWindowRec] = []
        for win in wins:
            raw, cleaned, diag, warped = self._images(ctx, gray, win)
            key = column_key(page, win.col)
            ctx.cache.put(ctx.book.id, "column_raw", key, raw)
            ctx.cache.put(ctx.book.id, "column_image", key, cleaned)
            b0, b1 = diag["band"]
            recs.append(ColumnWindowRec(
                col=win.col,
                left_line=VLineRec.of(win.left), right_line=VLineRec.of(win.right),
                top_y=float(win.top_y), bottom_y=float(win.bottom_y),
                border_top_y=float(win.border_top_y), border_bottom_y=float(win.border_bottom_y),
                border_top_in_column=float(win.border_top_in_column),
                border_bottom_in_column=float(win.border_bottom_in_column),
                raised=bool(win.raised),
                head_raise_inner_y=None if win.head_raise_inner_y is None else float(win.head_raise_inner_y),
                warped_size=(int(cleaned.shape[1]), int(cleaned.shape[0])),
                band=(int(b0), int(b1)),
                trim_top=BorderTrim(px=int(diag["top"]["px"]), case=str(diag["top"]["case"])),
                trim_bottom=BorderTrim(px=int(diag["bottom"]["px"]), case=str(diag["bottom"]["case"])),
                side_floor=round(side_floor(raw, p.side_floor_look, p.ink_threshold), 4),
                stamp_noise=round(stamp_noise_density(warped, p.ink_threshold), 4),
                # 在 `cleaned` 上量——判的是「削完之后还剩不剩框墨」，
                # 拿 raw/warped 量就成了「削之前有没有框」，那是另一件事
                **dict(zip(("frame_residue_top", "frame_residue_bottom"),
                           frame_residue(cleaned, (b0, b1), ink_threshold=p.ink_threshold))),
                # 分诊在**清理前**的 `raw` 上做：要判的正是「这一列清得拿不拿得准」，
                # 清完再判就只能看到清理的结果，看不到它当初面对的形态。
                triage=ColumnTriage(**{k: v for k, v in triage_column(raw).items() if k != "band"}),
            ))
        h, w = gray.shape[:2]
        return {"column_windows": PageWindows(
            page=page, page_size=(int(w), int(h)), vline_segments=int(borders.vline_segments),
            denoised=True, columns=recs)}

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        page, col, _ = parse_key(key)
        if col is None:
            raise ValueError(f"{kind_id} 的键必须带列号: {key}")
        gate: BorderDetectGateManifest = ctx.product("border_detect_gate_manifest", page)
        if gate.page_type_policy == "skip":
            raise KeyError(f"第 {page} 页页型判定为「{gate.page_type}」，没有列产物")
        gray, _, wins = self._windows(ctx, page)
        win = next((w for w in wins if w.col == col), None)
        if win is None:
            raise KeyError(f"第 {page} 页没有第 {col} 列")
        raw, cleaned, _, _ = self._images(ctx, gray, win)
        return raw if kind_id == "column_raw" else cleaned
