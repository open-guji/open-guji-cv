"""2a 单列拉直：射影变换 + 去噪。

五小步拆分（2026-11-25，`doc/2-切字/五小步.md`）：这里只留 2a——`page_column_windows` → `warp_column` →
`denoise_column`。定字带左右边、抹界行归 2b `column_band`，列端抹版框归 2c `column_end`。numeric 产物
`column_windows` 存窗口几何；列图 `column_raw`（矫正去噪）只进缓存，`render` 现算（确定性函数）。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, model_serializer

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.borders import Borders, VLineRec
from ..products.kinds.columns import ColumnWindowRec, PageWindows
from ..impl.keben.column import refine_top_by_frame
from ..seg.profile import column_profile, denoise_column, stamp_noise_density
from ..seg.warp import ColumnWindow, page_column_windows, warp_column


class ColumnWarpParams(BaseModel):
    body_pad: float = 0.0
    bottom_pad: float = 40.0          # 下界额外开的余量，见 column_projection.BOTTOM_PAD
    head_pad: float = 30.0            # 抬头列上界在抬头框线心之上再开的余量，见 column_projection.HEAD_PAD
    ink_threshold: int = 128
    min_blob_area: int = 6            # denoise_column
    side_floor_look: float = 0.25     # 交接闸 L2 用：两侧各看进去多少比例的宽度
    det_warp: bool = True
    """列射影改用跨 CPU 逐位确定的 numpy 双精度实现（`seg.warp._warp_perspective_det`，S9 2026-11-05）。
    cv2.warpPerspective 在 OpenCV 5 走浮点 SIMD，执行机与本机列图差 1 级灰度（册12 p99 每列 100+ 像素），
    下游切点跟着翻（012:99:1 dis_unet 151/154）。开了与 cv2 版也只在取整边上差 1 级，但仍改产物。
    2026-11-18 起缺省开（A22 切分开关收敛 11-13 定、A20 转缺省）：殿本、史記、全唐文早已写 true，`params_hash` 不变；
    没写的书（脉经、北行）column_warp 起过期。要旧行为写 `det_warp: false`（关时不进 dump，与转缺省前的缺省指纹相同）。"""
    ruled_warp: bool = False
    """列图不做射影，改「竖向线性、横向逐行按左右线插值」（`seg.warp.ruled_src_coords`，2026-11-08 A22）。缺省关＝射影。
    射影把左右线不平行（梯形）当透视，竖向按 1/(a+by) 伸缩。殿本 Commons 新图（第 7 轮换源）版面有真实弯曲，
    一列上下宽差可到 10%，列图竖向被拉伸 ±9%（r6 旧图 ±1–3%）：Step3 等距格网的相位对不上，整列错半格／一格，
    列首多出一条碎片格、列尾一格装两个字（vol49 p187 c7、vol80 p75 c1、vol81 p113 c1）。纸面字距是匀的，竖向该线性。
    开了下游 Step3/Step4 的列图→原图逆映射（`ColumnMapper.of`）按产物里的 `ruled` 跟着换。"""

    @model_serializer(mode="wrap")
    def _drop_off_switches(self, handler):
        """缺省关的开关不进 dump：没开的书 `params_hash` 与加字段之前逐位相同。"""
        d = handler(self)
        if isinstance(d, dict) and not self.ruled_warp:
            d.pop("ruled_warp", None)
        if isinstance(d, dict) and not self.det_warp:
            d.pop("det_warp", None)
        return d


def side_floor(raw: np.ndarray, look: float = 0.25, ink_threshold: int = 128) -> float:
    """两侧各外 look 里的最低墨占比，取两侧较大者。在**原始矫正图**上量，不是清理后。"""
    prof = column_profile(raw, ink_threshold=ink_threshold)
    k = max(1, int(round(look * len(prof))))
    return max(float(prof[:k].min()), float(prof[-k:].min()))


@register_step
class ColumnWarpStep(Step):
    spec = StepSpec(
        id="column_warp", title="2a 单列拉直（射影 + 去噪）", version="2.0", unit="column",   # 2.0：五小步拆分，只留拉直去噪；定字带归 column_band，列端抹框归 column_end
        consumes=("raw_page", "borders", "border_detect_gate_manifest"),
        produces=("column_windows", "column_raw"),
        params=ColumnWarpParams,
        code_deps=("open_guji_cv.seg.warp", "open_guji_cv.seg.profile", "open_guji_cv.impl.keben.column",
                   "open_guji_cv.impl.keben.border", "open_guji_cv.seg.polyline", "open_guji_cv.seg.frame_types"),
    )

    # ── 共用的一列计算 ────────────────────────────────────────────────
    def _windows(self, ctx: RunContext, page: int) -> tuple[np.ndarray, Borders, list[ColumnWindow]]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        gray = ctx.raw_page(page)
        borders: Borders = ctx.product("borders", page)
        wins = page_column_windows(borders.to_result(), body_pad=p.body_pad,
                                   bottom_pad=p.bottom_pad, head_pad=p.head_pad)
        # 上界之上还看得见版框、框与上界之间夹着字墨的列：把上界提到框下沿
        # （Step1 的整页直线落到真框之下时首字顶部整块不在列图里，见函数注释）
        # 双线版框的册不做：内框是细虚线、满宽段判据认不出，refine 会越过它去抓上面那道粗外框，
        # 把内框整条圈进列图（vol02 1682 列里 491 列被这样上提 15~25px，列首残线的大头）。
        # refine 是给单线框、Step1 线落在首字顶边的册（bxgb p48/p54）准备的。
        if int((ctx.book.frame_layers or {}).get("top", 1)) < 2:
            for win in wins:
                refine_top_by_frame(gray, win, det=p.det_warp, **({"ruled": True} if p.ruled_warp else {}))
        return gray, borders, wins

    def _images(self, ctx: RunContext, gray: np.ndarray, win: ColumnWindow) -> tuple[np.ndarray, np.ndarray]:
        """`(去噪后的列图 raw, 去噪前的矫正图 warped)`。"""
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        warped = warp_column(gray, win.left, win.right, win.top_y, win.bottom_y, det=p.det_warp, ruled=p.ruled_warp)
        raw = denoise_column(warped, ink_threshold=p.ink_threshold, min_blob_area=p.min_blob_area)
        return raw, warped

    # ── Step 接口 ───────────────────────────────────────────────────
    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        gate: BorderDetectGateManifest = ctx.product("border_detect_gate_manifest", page)
        if gate.page_type_policy == "skip":
            # 闸1 判定这页没有正文栏格（封面/书签/牌记）——射影/去噪都是白费功夫（page_type.py 模块头实测：书签页照切
            # 会切出 126 个无意义的块）。产出空列表。
            gray = ctx.raw_page(page)
            h, w = gray.shape[:2]
            borders: Borders = ctx.product("borders", page)
            return {"column_windows": PageWindows(
                page=page, page_size=(int(w), int(h)),
                vline_segments=int(borders.vline_segments), denoised=True, columns=[])}
        gray, borders, wins = self._windows(ctx, page)
        recs: list[ColumnWindowRec] = []
        for win in wins:
            raw, warped = self._images(ctx, gray, win)
            key = column_key(page, win.col)
            ctx.cache.put(ctx.book.id, "column_raw", key, raw)
            recs.append(ColumnWindowRec(
                col=win.col,
                left_line=VLineRec.of(win.left), right_line=VLineRec.of(win.right),
                top_y=float(win.top_y), bottom_y=float(win.bottom_y),
                border_top_y=float(win.border_top_y), border_bottom_y=float(win.border_bottom_y),
                border_top_in_column=float(win.border_top_in_column),
                border_bottom_in_column=float(win.border_bottom_in_column),
                raised=bool(win.raised),
                head_raise_inner_y=None if win.head_raise_inner_y is None else float(win.head_raise_inner_y),
                warped_size=(int(raw.shape[1]), int(raw.shape[0])),
                **({"ruled": True} if p.ruled_warp else {}),
                side_floor=round(side_floor(raw, p.side_floor_look, p.ink_threshold), 4),
                stamp_noise=round(stamp_noise_density(warped, p.ink_threshold), 4),
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
        raw, _ = self._images(ctx, gray, win)
        # 再生的列图尺寸须与产物记的 warped_size 一致（2026-11-25，CV4→CV0）：不一致说明产物是另一份配置／代码出的，
        # 下游按产物里的格坐标裁这张图就裁偏。宁可报错，不悄悄出偏图。产物缺席（还没跑过）不验。
        if ctx.has_product("column_windows", page):
            rec = ctx.product("column_windows", page).column(col)
            want = tuple(int(v) for v in rec.warped_size) if rec is not None and rec.warped_size else None
            got = (int(raw.shape[1]), int(raw.shape[0]))
            if want is not None and want != got:
                from ..core.step import StaleRenderError
                raise StaleRenderError(
                    f"{kind_id} {key} 再生尺寸 {got[0]}×{got[1]} 与产物 warped_size {want[0]}×{want[1]} 不符："
                    f"column_warp 产物不是按现在的代码／册配置出的，先从 column_warp 起重跑第 {page} 页。")
        return raw
