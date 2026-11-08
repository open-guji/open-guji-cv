"""Step2 单列射影变换 + 去噪 + 界行 / 版框清除。

包的是 `utils/column_projection` 的 page_column_windows → warp_column → denoise_column →
clean_column。numeric 产物存复现所需的全部量；两种列图（矫正去噪 / 清理后）只进缓存，
`render` 用同一条路径现算——射影与清理都是 (原图, Step1 线, 参数, 代码版本) 的确定性函数。
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, model_serializer

from ..core.spec import StepSpec, column_key, parse_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.border_detect_gate import BorderDetectGateManifest
from ..products.kinds.borders import Borders, VLineRec
from ..products.kinds.columns import BorderTrim, ColumnTriage, ColumnWindowRec, PageWindows
from ..books.siku_zongmu.column_triage import triage_column
from ..books.siku_zongmu.column import clean_column, refine_top_by_frame
from ..seg.profile import column_profile, denoise_column, stamp_noise_density
from ..seg.warp import ColumnWindow, page_column_windows, warp_column


#: `tight_rule_band`：内侧孤立窄条峰到这么高才当第二道线（写本「以」的左竖一条 240 行里峰 0.16~0.33）
TIGHT_INNER_BAR_PEAK = 0.5


class ColumnWarpParams(BaseModel):
    body_pad: float = 0.0
    bottom_pad: float = 40.0          # 下界额外开的余量，见 column_projection.BOTTOM_PAD
    head_pad: float = 30.0            # 抬头列上界在抬头框线心之上再开的余量，见 column_projection.HEAD_PAD
    ink_threshold: int = 128
    min_blob_area: int = 6            # denoise_column
    side_floor_look: float = 0.25     # 交接闸 L2 用：两侧各看进去多少比例的宽度
    det_warp: bool = False
    """列射影改用跨 CPU 逐位确定的 numpy 双精度实现（`seg.warp._warp_perspective_det`，S9 2026-11-05）。
    cv2.warpPerspective 在 OpenCV 5 走浮点 SIMD，执行机与本机列图差 1 级灰度（册12 p99 每列 100+ 像素），
    下游切点跟着翻（012:99:1 dis_unet 151/154）。开了与 cv2 版也只在取整边上差 1 级，但仍改产物。缺省关。"""
    tight_rule_band: bool = False
    """两侧界行判带收紧（写本开，史記）：贴边界行取衰减后的第一个谷（`column_text_band` first_valley），
    内侧孤立窄条峰到 TIGHT_INNER_BAR_PEAK 才当第二道线抹（缺省 0.10，殿本页边列内框淡到 0.12）。缺省关＝殿本旧行为。
    起因：写本字贴着界行写，「以」的左竖细高、跟右半「人」之间的缝比界行与字之间的缝还白，
    判带取窗口最低点、或把它当内框，都连界行一起抹白，Step4 拿到的字就缺一笔（SJ r5，02:27:1:4b、02:112:2:2b）。"""

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
        if isinstance(d, dict) and not self.tight_rule_band:
            d.pop("tight_rule_band", None)
        if isinstance(d, dict) and not self.det_warp:
            d.pop("det_warp", None)
        return d


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
        id="column_warp", title="Step2 单列射影 + 去噪 + 清理", version="1.6", unit="column",   # 1.6：refine_top_by_frame 的「top_y 已在框上」否决加例外：上面另有满宽段、中间先白后连续 ≥20 行字墨（top_y 那道满宽段是首字顶横／夹注两字顶齐，SJ 查史記 02:5「姓」「岳時」），照常提到上面框下沿；殿本全 99 册只动 vol82 p147 c6
        consumes=("raw_page", "borders", "border_detect_gate_manifest"),
        produces=("column_windows", "column_raw", "column_image"),
        params=ColumnWarpParams,
        code_deps=("open_guji_cv.seg.warp", "open_guji_cv.seg.profile", "open_guji_cv.books.siku_zongmu.column", "open_guji_cv.books.siku_zongmu.border", "open_guji_cv.seg.polyline", "open_guji_cv.seg.frame_types",
                   "open_guji_cv.books.siku_zongmu.column_triage"),
        # 双线版框剥第二道读册配置（2026-09-26）——改 yaml 要让列图过期
        book_deps=("frame_layers", "outer_gap"),
    )

    # ── 共用的一列计算 ─────────────────────────────────────────────────
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

    def _images(self, ctx: RunContext, gray: np.ndarray, win: ColumnWindow
                ) -> tuple[np.ndarray, np.ndarray, dict, np.ndarray]:
        p: ColumnWarpParams = ctx.params_for(self)  # type: ignore[assignment]
        warped = warp_column(gray, win.left, win.right, win.top_y, win.bottom_y, det=p.det_warp, ruled=p.ruled_warp)
        raw = denoise_column(warped, ink_threshold=p.ink_threshold, min_blob_area=p.min_blob_area)
        # 双线版框剥第二道（column_projection.LAYER2_* 注）：层数与层距来自册配置
        fl, og = ctx.book.frame_layers or {}, ctx.book.outer_gap or {}
        cleaned, diag = clean_column(
            raw, ink_threshold=p.ink_threshold,
            layers=(int(fl.get("top", 1)), int(fl.get("bottom", 1))),
            layer_gap=(og.get("top"), og.get("bottom")),
            inner_bottom=win.border_bottom_in_column,
            **({"bar_after_min_peak": TIGHT_INNER_BAR_PEAK, "first_valley": True} if p.tight_rule_band else {}))
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
                **({"ruled": True} if p.ruled_warp else {}),
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
