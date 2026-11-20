"""Step1 边框探测：原图 → 版框（上下内外）+ 界行（含三段折线）+ 抬头框 + 列类型。

包的是 `utils/border_geometry.detect_borders`，输入直接是**原始扫描**（不经 s1..s6），
输出坐标天然是右上原点规范空间。

另产 `line_index`（与现代链 `line_detect` **同一种产物**）：逐列位记类型
`body | margin | edge`，下游据此把非正文列排除在外。筒子页（`leaf_layout: folio`）
的版心就是靠它标成 `margin` 的——判据与两条负结果见 `impl/keben/column_types.py`。
一页一个半叶的书（`leaf_layout: single`，即默认）只会标出 `edge`，其余全是 `body`，
与加这套东西之前的行为等价。

`BookSpec.column_grid` 开了走网格模式（界行没印全的书，见
`peak_line_search.find_vertical_lines_grid`）：`borders.vline_filled` 标出插值的线，
`line_index` 里两侧至少一条界行是插值的列位加 `rule_interpolated` 旗标。
"""

from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel, Field, model_serializer

from ..core.book import _expand_pages
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.borders import Borders
from ..products.kinds.line_index import LineIndex, LineRec
from ..impl.keben.border import detect_borders, refit_bends
from ..impl.keben.column_types import classify_columns
from ..impl.keben.pitch_rescue import rescue as pitch_rescue
from ..seg.columns import COL_WIDTH_FLAG, ColumnSpec, check_columns

#: `grid_free_fallback`：贴线字缝带，离线 [GUTTER_IN, GUTTER_OUT] 倍列距。
GUTTER_IN, GUTTER_OUT = 0.036, 0.075
#: 自由模式的穿字分要低于网格模式的这个比例才换。
GRID_FREE_RATIO = 0.5


def gutter_ink_score(res, gray, ink_threshold: int = 128) -> float:
    """内竖线「穿字」分：内线两侧贴线字缝带的墨比例 ÷ 版心（首末线之间）的平均墨比例。

    线落在字缝（或界行两侧的白缝）里≈0；线整片错位、斜穿字身时≈1 或更高。只量版框中段（页高 25%–85%），
    版心几乎没墨（空页）记 0。坐标与 `trim_outer_columns` 同：`res.verticals` 右上原点，图上 x = W-1-x。"""
    import numpy as np
    v = res.verticals
    if len(v) < 3:
        return 0.0
    H, W = gray.shape[:2]
    y0, y1 = int(H * 0.25), int(H * 0.85)
    ys = np.arange(y0, y1, 4)
    ink = gray[ys] < ink_threshold                                       # 行抽样
    xm = [float(line.x_at(res.height / 2.0)) for line in v]
    pitch = float(np.median(np.diff(sorted(xm))))
    lo, hi = int((W - 1) - max(xm)), int((W - 1) - min(xm))
    if pitch <= 0 or hi - lo < 2:
        return 0.0
    page = float(ink[:, max(lo, 0):min(hi, W)].mean())
    if page < 0.02:
        return 0.0
    ds = list(range(int(GUTTER_IN * pitch), int(GUTTER_OUT * pitch) + 1))
    ds = [-d for d in ds] + ds
    rows = np.arange(len(ys))[:, None]
    near = []
    for line in v[1:-1]:
        xs = np.round((W - 1) - line.x_at(ys)).astype(int)
        cols = np.clip(xs[:, None] + np.array(ds)[None, :], 0, W - 1)
        near.append(float(ink[rows, cols].mean()))
    return float(np.mean(near)) / page


#: `edge_strip`：书口条判据。天头（页高前 `EDGE_TOP` 比例）里逐列墨比例 > `EDGE_INK` 算书口条墨；从页边往里走，
#: 先放过页边留白 `EDGE_SKIP` px（墨层 `edge_margin` 清过的那一圈），连续 `EDGE_GAP` px 不是书口条墨就停；最多走页宽的 `EDGE_SIDE`。
EDGE_TOP, EDGE_INK, EDGE_SKIP, EDGE_GAP, EDGE_SIDE = 0.06, 0.5, 40, 12, 0.07


def strip_page_edge(gray, ink_threshold: int = 128):
    """把页边的书口条（叠着的书页边缘，二值后成一束贯穿天头到地脚的竖黑条）抹白，返回 (新图, 左抹宽, 右抹宽)。

    真版框线只在上下版框之间，天头没有；书口条从天头一直通到页底，二值化以后比细内框线更像「框」，网格模式会把外框
    定在书口边上、内插线整片偏（脉经 03 p42：真内框 x≈2366，网格框到 2428；03 p46 右边 5 条线跟着偏）。只抹页边
    连着的那一束，天头有零星墨、脏页不会一路抹进版心（脉经各册末页书衣实测）。"""
    import numpy as np
    H, W = gray.shape[:2]
    f = (gray[: max(1, int(H * EDGE_TOP))] < ink_threshold).mean(0)
    lim = int(W * EDGE_SIDE)
    out, cut = gray, [0, 0]
    for side in (0, 1):
        xs = range(0, lim) if side == 0 else range(W - 1, W - 1 - lim, -1)
        last, miss = None, -EDGE_SKIP
        for x in xs:
            if f[x] > EDGE_INK:
                last, miss = x, 0
            else:
                miss += 1
                if miss > EDGE_GAP:
                    break
        if last is not None:
            if out is gray:
                out = gray.copy()
            if side == 0:
                out[:, : last + 1] = 255; cut[0] = last + 1
            else:
                out[:, last:] = 255; cut[1] = W - last
    return out, cut[0], cut[1]


#: 页级网格页上，最外一列比内列中位窄到这个比例以下，就把外框线按中位列距往外推。
OUTER_NARROW_FRAC = 0.8


def pad_outer_columns(res) -> int:
    """`column_grid_pages` 点名页专用：最外一列明显窄于内列（< `OUTER_NARROW_FRAC` × 内列
    中位），说明那侧版框没印全、外框线落到了字上（殿本 vol04 p63：右框只下三分之一有墨，
    探到的「框」是第一列字的笔画，首列只剩 117px，半列字丢了）。把那条外框线按内列中位
    列距往外推、记成插值线。只动外框两条，内部界行不动；推出图外就不推。返回推了几条。"""
    v = res.verticals
    if len(v) < 5:
        return 0
    y = res.height / 2.0
    xs = [float(line.x_at(y)) for line in v]
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    inner = sorted(gaps[1:-1])
    med = inner[len(inner) // 2]
    filled = list(res.vline_filled) or [False] * len(v)
    n = 0
    for idx, gap, sign in ((0, gaps[0], -1.0), (len(v) - 1, gaps[-1], 1.0)):
        if gap >= OUTER_NARROW_FRAC * med:
            continue
        shift = sign * (med - gap)
        if not 0 <= xs[idx] + shift <= res.width - 1:
            continue
        v[idx] = replace(v[idx], x_at_top=v[idx].x_at_top + shift)
        filled[idx] = True
        n += 1
    if n:
        res.vline_filled = filled
    return n


#: `grid_outer_trim` 找内侧细线时，搜索窗是「内邻线 + 中位列距」两侧各这么多倍 `grid_thresholds` 的 slot_tol；
#: 找到的线离原外框线不到这么多倍 slot_tol 就不认（窗口够得着原外框线时，联合搜索会挑回它：脉经 02:50 首列
#: 外线 119、目标 147，slot_tol 29 的窗里最强的就是原线）。
OUTER_TRIM_TOL = 0.5
OUTER_TRIM_AWAY = 0.5


#: 外列宽过内列中位这么多倍就不是「多圈进一条书口」了（列网整体不对、非正文页），不动。
OUTER_TRIM_MAX = 1.6


def trim_outer_columns(res, gray, ratio: float, *, n_cols: int | None = None, ink_threshold: int = 128,
                       col_pitch: float | None = None, frame_height: float | None = None,
                       gap_only: bool = False) -> int:
    """网格模式书级开关 `grid_outer_trim`：`pad_outer_columns` 的镜像——最外一列明显**宽于**内列
    （> `ratio` × 内列中位），说明外框线落到了版心条（书口鱼尾、书名卷次小字）外沿上，书口整条圈进了
    首／末列（脉经 02:50 c1 列宽 238，正文 0–180、内界线≈190、书口 195–255；网格模式选版框对时无界行的
    页各对支持数打平，按投影和挑中墨更重的鱼尾那条）。

    外框线改到「内邻线往外一个中位列距」：先在那附近（± 半个 slot_tol）用联合搜索找细线（`is_thin_rule`，
    同网格模式验线那把尺子），找到就按它定位；找不到就按中位列距平移、记插值（`vline_filled`）。
    线形一律取内邻线平移（折线页也一样，整页同为直线或三段），只改位置。只动外框两条，内部线不动。
    列数不等于 `n_cols`（本页版式列数）的页、外列宽过 `OUTER_TRIM_MAX` 倍的不动（序页、书衣等列网本来不对的页，
    脉经 02 p4／p77 外推 350–415px）。返回改了几条。"""
    import numpy as np
    from ..impl.keben.border import _vline_to_new
    from ..seg.grid import grid_thresholds, is_thin_rule
    from ..seg.lines import joint_search_coarse_to_fine
    v = res.verticals
    if ratio <= 0 or len(v) < 5 or (n_cols is not None and len(v) != n_cols + 1):
        return 0
    H, W = gray.shape[:2]
    y = res.height / 2.0
    xs = [float(line.x_at(y)) for line in v]
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    inner = sorted(gaps[1:-1])
    med = inner[len(inner) // 2]
    thr = grid_thresholds(col_pitch or med, frame_height)
    tol = OUTER_TRIM_TOL * thr["slot_tol"]
    mask = None
    filled = list(res.vline_filled) or [False] * len(v)
    n = 0
    for idx, nb, gap, sign in ((0, 1, gaps[0], -1.0), (len(v) - 1, len(v) - 2, gaps[-1], 1.0)):
        if not ratio * med < gap <= OUTER_TRIM_MAX * med:
            continue
        target = xs[nb] + sign * med                     # 新坐标（右上原点）里，外框线该在的 x
        if mask is None:
            mask = (gray < ink_threshold).astype(np.float64)
        c_old = (W - 1) - target                         # 换回左上原点找线
        lo, hi = int(round(c_old - tol)), int(round(c_old + tol))
        hit = False
        if 0 <= lo and hi <= W - 1:
            m = joint_search_coarse_to_fine(mask, "v", lo, hi)
            if is_thin_rule(m, thr["min_score"], thr["max_width"]):
                # 找到的线只取位置（框中高处），线形跟内邻线
                found = float(_vline_to_new(m, W, H).x_at(y))
                if abs(found - xs[idx]) >= OUTER_TRIM_AWAY * thr["slot_tol"]:
                    target, hit = found, True
        if not (xs[nb] < target < xs[idx] if sign > 0 else xs[idx] < target < xs[nb]):
            continue
        if gap_only and not hit:
            # `grid_outer_fix`：没找到细线、按列距平移的落点得在字缝里，不然是外列本来就宽（版框留白），不收
            between = _band_ink(gray, ink_threshold)
            # 参照：本页满列字身的墨（各内列中段墨的 3/4 分位；短列、空列不拉低）。落点靠版心那半边（外半边可能
            # 就是书口条的墨）逐列墨中位到了它的 `OUTER_TRIM_GAP_INK` 倍，就是压着字（细界行、纸面杂点只占几列，不抬中位）
            col_ink = sorted(between(xs[i] + 0.2 * gaps[i], xs[i + 1] - 0.2 * gaps[i]) for i in range(1, len(xs) - 2))
            ref = col_ink[(3 * len(col_ink)) // 4]
            w = GUTTER_OUT * med
            if between(target, target - sign * w, stat="median") >= OUTER_TRIM_GAP_INK * ref:
                continue
        v[idx] = replace(v[nb], x_at_top=v[nb].x_at_top + (target - xs[nb]))
        filled[idx] = not hit
        n += 1
    if n:
        res.vline_filled = filled
    return n


#: `grid_outer_fix`：外列宽不到内列中位这么多倍、里面的墨又不到版心平均的 `OUTER_SLIVER_INK`，就是版框内侧白边
#: 上多出的一条线（脉经 02 p15：粗版框与首列字之间 70px 空白被当成一列，另一侧版框没认、整列字落在网外）。
OUTER_SLIVER_FRAC = 0.5
OUTER_SLIVER_INK = 0.5
#: 另一侧补外框线：在「外框线往外 [lo, hi] 倍列距」里找最实的竖线（版框）；外框线往外 `OUTER_ADD_TEXT` 倍列距里
#: 的墨得有版心平均的 `OUTER_ADD_INK` 倍以上（那边确有一列字落在网外）才补。
OUTER_ADD_RANGE = (0.6, 1.45)
OUTER_ADD_TEXT = 0.6
OUTER_ADD_INK = 0.3
#: `grid_outer_fix` 下收外框线找不到细线、按列距平移时，落点靠版心一侧贴线带的墨（逐列中位）得不到内邻列字身墨的这个比例（在字缝里）
OUTER_TRIM_GAP_INK = 0.5


def _band_ink(gray, ink_threshold: int):
    """页高 25%–85% 的行抽样墨图，和一个「新坐标 [a, b] 之间的墨比例」量具（新坐标右上原点，图上 x = W-1-x）。"""
    import numpy as np
    H, W = gray.shape[:2]
    ink = gray[np.arange(int(H * 0.25), int(H * 0.85), 4)] < ink_threshold

    def between(a: float, b: float, stat: str = "mean") -> float:
        lo, hi = sorted((int(round((W - 1) - a)), int(round((W - 1) - b))))
        lo, hi = max(lo, 0), min(hi, W - 1)
        if hi <= lo:
            return 0.0
        blk = ink[:, lo:hi + 1]
        return float(np.median(blk.mean(axis=0))) if stat == "median" else float(blk.mean())
    return between


def fix_outer_sliver(res, gray, *, n_cols: int | None = None, ink_threshold: int = 128) -> int:
    """`grid_outer_fix`：一侧外列是空白窄条（< `OUTER_SLIVER_FRAC` × 内列中位、墨 < `OUTER_SLIVER_INK` × 版心平均）
    时，去掉窄条外侧那条线（粗框条／双边框外线；里侧那条是双边框内线或字区起点，留着当外框线），在另一侧外框线往外 `OUTER_ADD_RANGE` 倍列距里找最实的竖线当版框补上。
    另一侧外框线外面得确有字（墨 ≥ `OUTER_ADD_INK` × 版心平均），否则不动。线形取那一侧外框线平移。
    列数不等于 `n_cols` 的页不动。返回改了几处（0／1）。"""
    from ..impl.keben.border import _vline_to_new
    from ..seg.lines import joint_search_coarse_to_fine
    import numpy as np
    v = res.verticals
    if len(v) < 5 or (n_cols is not None and len(v) != n_cols + 1):
        return 0
    H, W = gray.shape[:2]
    y = res.height / 2.0
    xs = [float(line.x_at(y)) for line in v]
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    med = sorted(gaps[1:-1])[len(gaps[1:-1]) // 2]
    between = _band_ink(gray, ink_threshold)
    page = between(xs[0], xs[-1])
    if med <= 0 or page <= 0.02:
        return 0
    n = len(v)
    for out, inn, gap in ((0, 1, gaps[0]), (n - 1, n - 2, gaps[-1])):
        # 窄条里量逐列墨的中位（双边框的内细线、粗框条的毛边都只占几列，不抬中位）；外半边常压着粗框条，只量靠里的
        if gap >= OUTER_SLIVER_FRAC * med or between(xs[inn] + 0.15 * gap * (1 if out else -1),
                                                      xs[inn] + 0.6 * gap * (1 if out else -1),
                                                      stat="median") >= OUTER_SLIVER_INK * page:
            continue
        opp = n - 1 if out == 0 else 0
        sign = 1.0 if opp == n - 1 else -1.0                    # 另一侧往外的方向（新坐标）
        if between(xs[opp], xs[opp] + sign * OUTER_ADD_TEXT * med) < OUTER_ADD_INK * page:
            continue
        a, b = (xs[opp] + sign * OUTER_ADD_RANGE[0] * med, xs[opp] + sign * OUTER_ADD_RANGE[1] * med)
        lo, hi = sorted((int(round((W - 1) - a)), int(round((W - 1) - b))))
        lo, hi = max(lo, 0), min(hi, W - 1)
        if hi - lo < 0.3 * med:
            continue
        m = joint_search_coarse_to_fine((gray < ink_threshold).astype(np.float64), "v", lo, hi)
        if m.score <= 0:
            continue
        found = float(_vline_to_new(m, W, H).x_at(y))
        filled = list(res.vline_filled) or [False] * n
        straight = list(res.verticals_straight)
        new_v = replace(v[opp], x_at_top=v[opp].x_at_top + (found - xs[opp]))
        keep = [i for i in range(n) if i != out]
        lines, fl = [v[i] for i in keep], [filled[i] for i in keep]
        st = [straight[i] for i in keep] if len(straight) == n else straight
        if opp == n - 1:
            lines.append(new_v); fl.append(False)
            if len(straight) == n:
                st.append(replace(straight[opp], x_at_top=straight[opp].x_at_top + (found - xs[opp])))
        else:
            lines.insert(0, new_v); fl.insert(0, False)
            if len(straight) == n:
                st.insert(0, replace(straight[opp], x_at_top=straight[opp].x_at_top + (found - xs[opp])))
        res.verticals = lines
        res.vline_filled = fl
        if len(straight) == n:
            res.verticals_straight = st
        return 1
    return 0


def apply_head_raise_verdicts(res, verdicts: dict[int, int], n_rows: int, scale: float = 1.0) -> dict[int, int]:
    """人裁逐列抬头（`lookup.resolved_head_raise`，本页 `col → n_raised`）改写 `res.head_raise`，返回改了的列。

    判 0 的列去掉 Step1 认的抬头框；判 n ≥ 1 而 Step1 没认的列补一个 `estimated` 抬头框。补的框高：本页有
    Step1 认下的抬头列就取它们离主上版框的中位距离（同页抬头框一样高），没有就取一格高（版框高 / `n_rows`）；
    多抬一级多加一格。内外框间距同理取本页中位，没有就按内框往上 `HR_DEFAULT_PAIR_GAP`（乘本册 `head_raise_scale`）。
    Step1 已认的抬头列不动（框是量出来的，比估的准）。"""
    from statistics import median

    from ..impl.keben.border import HR_DEFAULT_PAIR_GAP
    from ..seg.frame_types import HeadRaiseBorder
    if not verdicts or len(res.verticals) < 2:
        return {}

    def btop(col: int) -> float:      # 同 detect_head_raise：主上版框在该列两条界行处的平均高度
        return sum(res.top.y_at(v.x_at(0.0)) for v in res.verticals[col - 1:col + 1]) / 2.0

    n_cols = len(res.verticals) - 1
    have = {h.col for h in res.head_raise}
    measured = [h for h in res.head_raise if h.col <= n_cols]
    cell = (res.bottom.y_at(0.0) - res.top.y_at(0.0)) / n_rows
    dist = median(btop(h.col) - h.inner_y for h in measured) if measured else cell
    gap = median(h.inner_y - h.outer_y for h in measured) if measured else HR_DEFAULT_PAIR_GAP * scale
    done: dict[int, int] = {}
    for col, n in sorted(verdicts.items()):
        if not 1 <= col <= n_cols:
            continue
        if n == 0 and col in have:
            res.head_raise = [h for h in res.head_raise if h.col != col]
            done[col] = 0
        elif n >= 1 and col not in have:
            inner = btop(col) - dist - (n - 1) * cell
            res.head_raise.append(HeadRaiseBorder(col=col, inner_y=float(inner), outer_y=float(inner - gap),
                                                  estimated=True))
            done[col] = n
    res.head_raise.sort(key=lambda h: h.col)
    return done


def _apply_vline_override(res, xs: list[float]) -> None:
    """`vline_overrides`：用人核界行替换探到的竖线（按直线），`vline_filled` 全记人核（False）。"""
    import dataclasses
    from ..seg.frame_types import VLine
    top_y = float(res.top.y_at(0.0)) if res.top is not None else 0.0
    bot_y = float(res.bottom.y_at(0.0)) if res.bottom is not None else float(res.height - 1)
    y_mid = (top_y + bot_y) / 2.0
    old = [(float(v.x_at(y_mid)), float(v.slope)) for v in res.verticals]
    new = []
    for x in sorted(float(x) for x in xs):
        sl = min(old, key=lambda t: abs(t[0] - x))[1] if old else 0.0
        new.append(VLine(x_at_top=x - sl * y_mid, slope=sl))
    res.verticals = new
    res.verticals_straight = list(new)
    res.vline_segments = 1
    res.vline_filled = [False] * len(new)


class BorderDetectParams(BaseModel):
    expected_cols: int | None = Field(default=None, description="列数先验；None = 用 Book 的 expected_cols")
    ink_threshold: int = 128

    column_grid_pages: list[int | str] = []
    """页级网格模式：点名的页竖线走 `column_grid`（版框定死、列距均匀），其余页照书级配置。
    用在界行断续、自由模式挑了假竖线或漏了一条界行、整列没切出来的页，例如殿本 vol05 p55／
    p123、vol04 p80（2026-10-19）。写法同 `column_gate.period_prior_pages`：
    `params: {border_detect: {column_grid_pages: [55, 123], grid_col_pitch: 185}}`。
    缺省空，空时本字段与 `grid_col_pitch` 都不进参数 dump，产物与加字段前逐字节相同。"""
    grid_col_pitch: float | None = None
    """`column_grid_pages` 那些页用的列距先验（px）；None = 用书级 `col_pitch`。"""
    grid_lattice_fallback: bool = False
    """`column_grid_pages` 那些页上，网格模式选不出版框对（版框那条线不在候选池里）时，按已探到的
    细界行拟等距网格、在图内框出 `expected_cols` 列再逐槽验线（`peak_line_search.lattice_frame_pair`），
    不再退回截断。殿本换源 vol12 p139（GUJI-748）：右版框贴图边、左边带进邻叶版心，上下外框都没探到，
    网格模式与自由模式结果相同、只出 8 列。写法
    `params: {border_detect: {column_grid_pages: [139], grid_col_pitch: 133, grid_lattice_fallback: true}}`。
    只管点名页；缺省关不进参数 dump，产物与加字段前逐字节相同。"""
    grid_outer_trim: float = 0.0
    """网格模式（书级 `column_grid` 或点名页）下，首／末列宽于内列中位这么多倍就把外框线收到「内邻线往外一个
    中位列距」，先就近找细线、找不到按列距平移（`trim_outer_columns`）。给半叶图书口紧贴版框、网格模式把书口
    外沿当版框的书用（脉经，2026-11-18，GUJI-774）：`params: {border_detect: {grid_outer_trim: 1.12}}`。
    0＝关（缺省），不进参数 dump，产物与加字段前逐字节相同。"""
    grid_free_fallback: float = 0.0
    """书级网格模式下，内竖线穿字分（`gutter_ink_score`）高过这个值，就再用自由模式（＋列距救援）探一遍，
    线数相同且穿字分不到网格模式的 `GRID_FREE_RATIO` 就改用自由模式的线。给界行大多没印出来、网格靠插值补线，
    但个别页列距不匀、补出的线整片错位斜穿字的书用（脉经 02 p15、03 p40，2026-11-18，GUJI-774）：
    `params: {border_detect: {grid_free_fallback: 0.15}}`。0＝关（缺省），不进参数 dump，产物与加字段前逐字节相同。"""
    grid_outer_fix: bool = False
    """书级网格模式下外框线的后处理（在 `grid_free_fallback` 换线之后做，换没换线都做）：①外列是空白窄条就去掉窄条
    外侧那条线、在另一侧找版框补一列（`fix_outer_sliver`）；②开了 `grid_outer_trim` 的，收外框线挪到这一步做，
    而且找不到细线时只在落点是字缝的情况下按列距平移（外列本来就宽、是版框留白的不收）。脉经 02 p15（左边版框内白边
    多一条线、右边整列落在网外）、02 p24（换线后右线落在书口上），2026-11-18 用户指出。缺省关，不进参数 dump。"""
    edge_strip: bool = False
    """探竖线之前先把页边书口条抹白（`strip_page_edge`）：书口条从天头通到页底，二值化（册 `ink`）后成一束竖黑条，
    比细内框线更像框，把外框吸到书口边（脉经 03 p42、03 p46，2026-11-19 用户指出、A22 定位）。只给 `detect_borders`
    用，穿字分、外框修整等仍看原图。缺省关，不进参数 dump。"""
    pitch_rescue: bool = True
    """列距救援（`impl/keben/pitch_rescue`，2026-10-23 sheldon 定缺省开）：自由模式探出的页上有一条列
    < 0.7 × 中位列宽（多挑了假竖线、外侧一整列落到网外）时，先用网格模式重探，选不出版框对再
    「去掉劈开窄对的线、在有字的一侧补外框线」，再不成就从自由线、网格线、外推外框线里拼一串等宽列（fuse）；
    新列网干净才接受。没触发的页逐字节不变。"""

    head_raise_scale: float = 1.0
    """抬头框探测的像素尺度（`border_geometry.HR_SCALE_LENGTHS`，2026-10-26，GUJI-748）：本册图相对殿本旧图
    的缩放比。那组长度常数是在旧图上量的绝对像素，换图源 siku-qiefen-v2（约 0.70 倍）后抬头框整片认不出
    （vol07 新 p43 五列抬头全丢）。换源的册与 `bottom_gap`、`period_prior` 乘同一个缩放比，如
    `params: {border_detect: {head_raise_scale: 0.7021}}`。缺省 1.0 不进参数 dump，产物与加字段前逐字节相同。"""

    top_weak_ratio: float = 0.3
    """上版框弱线护栏的门槛（1.20，`seg/lines._weak_top_guard`）：选中的上框线横向墨量不到带里最强横线的这个比例才动。
    缺省 0.3 是殿本定的（16516 页只动 15 页；再高会把抬头页主框换成抬头框顶线）。写本（史記文淵閣本）框条下有一道细虚线、
    首行字顶齐平，线落在字顶时墨量是最强线的 0.30–0.42，册配置写 `params: {border_detect: {top_weak_ratio: 0.45,
    top_weak_floor: 0.25}}`。缺省值不进参数 dump。"""

    top_weak_floor: float | None = None
    """弱线护栏改取哪条线（1.20）：None＝取投影 ≥ `top_weak_ratio`、在选中线之上最靠页心的一条，挪不够 0.021 页高就不动（殿本）；
    给了值＝先只留离选中线 ≥0.021 页高、投影 ≥ 这个比例的线，再取最靠页心的一条（写本：要越过字顶附近的碎横、落到框条下那道细虚线）。"""

    bottom_weak_ratio: float = 0.0
    """下版框弱线护栏（`seg/lines._weak_bottom_guard`，2026-11-08）：选中的下框线横向墨量不到带里最强横线的这个比例、
    它下方 ≥0.021 页高处另有够强的横线，改取最靠页心的那条（只往下挪）。殿本 vol20–99 新图源写 0.3（13,320 页只动 17 页、
    看图全对：末行字底／淡横被当下框，整页少切一格或切掉字脚）。缺省 0＝关，不进参数 dump，产物与加字段前逐字节相同。
    配了 `bottom_gap` 的册（vol01–19）有跨页先验救援，不用开。"""

    bottom_lock_reslope: bool = False
    """下框贴搜索带边界时连倾角一起重找（`seg/lines.find_horizontal_border` 的 `lock_reslope`，2026-11-08）：
    贴边的 primary 是截断伪影，倾角也是假的（vol12 p27 新图挑了 0.047 的斜角），沿它找非边界峰找不回倾角≈0 的真框，
    下框停在末三四个字中间、各列末 2–4 字没格。开了在粗扫各档倾角里找非边界峰，分数超过原倾角最好峰 2 倍才换。
    殿本 99 册新图只有贴边页受影响（普查见 PR）。缺省关，不进参数 dump，产物与加字段前逐字节相同。"""

    top_edge_reslope: bool = False
    """上框贴图顶时连倾角一起重找（`seg/lines.find_horizontal_border` 的 `top_edge_reslope`，2026-11-08）：殿本 Commons 新图
    按版框裁、上方只留 pad，抬头框顶／纸边暗条贴着图顶，联合搜索在图顶截断处拿到窄峰高分、倾角也是假的（vol14 p45 y=0、
    倾角 0.035，真框在 128–146 行），整页上框、抬头全错。开了贴图顶时在 ±0.05 各档倾角里找离开图顶的最好峰。
    缺省关，不进参数 dump，产物与加字段前逐字节相同。"""

    expected_cols_pages: dict[int, int] = {}
    """按页列数（2026-11-12，殿本 vol01 p100：图上 10 列、版框只探出 9 列，参校本质检）：`{页: 本页列数}`，覆盖册级 `expected_cols`。
    职名页、个别页列数与册级不同时用；一般同 `vline_overrides` 配用（给出本页全部竖线）。border_detect、border_detect_gate、
    column_gate 三处都要写同一张表。缺省空，空时不进参数 dump，产物与加字段前逐字节相同。"""
    vline_overrides: dict[int, list[float]] = {}
    """页级人核竖线（2026-11-02，史記文淵閣本 06 p63、04 p122 类）：自由／网格模式在右（左）外框被扫描裁掉、
    小注双行带内多出一条假界行的页上都挑不对界行（整列漏掉、小注缝被当成列界）。点名的页用人核给的界行
    **右上原点 x（与 `borders.verticals` 同一空间：离页右缘的距离，版框中高处，升序＝右→左）**整串替换探到的竖线；每条线的斜率取探到的最近一条（没有就 0），一律按直线。
    写法 `params: {border_detect: {vline_overrides: {63: [0, 167, 363, 562, 775, 1055, 1274, 1484, 1735]}}}`。
    缺省空，空时本字段不进参数 dump，产物与加字段前逐字节相同。"""

    hline_hints: dict[int, dict[str, float]] = {}
    """页级人给上／下版框位置（2026-11-09，GUJI-758，殿本第 9 轮上版框认错 10 页）：抬头框顶贴图顶的页，自动探测把抬头框顶
    当成上版框，整页抬头认不出、列窗整体上移。点名的页给那条框线在**页面横向中点处的 y**（左上原点行号）：线就放在这个 y，
    倾角取附近 ±`seg/lines.HINT_RADIUS_FRAC`×页高（殿本 ±53px）里最强横线（粗框条）的；折线、抬头框、外框都在这条线上算。
    殿本按「框条内沿约定」给粗框条下面那道细线的 y（自动探到的页也取它）。给了 `bottom` 时不再「推到下框条」。写法
    `params: {border_detect: {hline_hints: {156: {top: 187}, 27: {top: 210, bottom: 2580}}}}`。
    缺省空，空时不进参数 dump，产物与加字段前逐字节相同；只有写了的页结果变。"""

    bend_w80_med: float | None = None
    """弯页门槛（页级界行 w80 中位，px；`seg/polyline.fit_vlines_polyline` 的 `w80_med_min`）：中位不到它、任一条也不到
    `BEND_W80_MAX` 的页按直线页走，否则整页三段折线。None＝代码常数 `BEND_W80_MED`（7）。写 0＝量得出 w80 的页一律三段折线
    （书级 `vline_polyline: false` 仍优先）。殿本第7轮换 Commons 图源后界行清楚、w80 中位约 6，约一半的页判成直线页；
    Step2 直线列整列一个单应，把列宽上下 5–10% 的差变成字距上疏下密，row_segment 等距格网优先就把列首列尾的字切半
    （R02 碰裁边 17%→30%，ai-team domain/CV/质检/待审原因深挖/R02-第7轮列端切半-A20）。殿本在 book_defaults 写
    `params: {border_detect: {bend_w80_med: 0}}`。缺省 None 不进参数 dump，产物与加字段前逐字节相同。"""

    @model_serializer(mode="wrap")
    def _drop_off_merge(self, handler):
        """缺省关时不进 dump：没开的书 `params_hash` 与加这个字段之前逐位相同。"""
        d = handler(self)
        if isinstance(d, dict) and not self.column_grid_pages:
            d.pop("column_grid_pages", None)
            d.pop("grid_col_pitch", None)
        if isinstance(d, dict) and not self.grid_outer_trim:
            d.pop("grid_outer_trim", None)
        if isinstance(d, dict) and not self.grid_free_fallback:
            d.pop("grid_free_fallback", None)
        if isinstance(d, dict) and not self.grid_outer_fix:
            d.pop("grid_outer_fix", None)
        if isinstance(d, dict) and not self.edge_strip:
            d.pop("edge_strip", None)
        if isinstance(d, dict) and not self.grid_lattice_fallback:
            d.pop("grid_lattice_fallback", None)
        if isinstance(d, dict) and self.head_raise_scale == 1.0:
            d.pop("head_raise_scale", None)
        if isinstance(d, dict) and self.top_weak_ratio == 0.3:
            d.pop("top_weak_ratio", None)
        if isinstance(d, dict) and self.top_weak_floor is None:
            d.pop("top_weak_floor", None)
        if isinstance(d, dict) and not self.bottom_weak_ratio:
            d.pop("bottom_weak_ratio", None)
        if isinstance(d, dict) and not self.bottom_lock_reslope:
            d.pop("bottom_lock_reslope", None)
        if isinstance(d, dict) and not self.top_edge_reslope:
            d.pop("top_edge_reslope", None)
        if isinstance(d, dict) and not self.expected_cols_pages:
            d.pop("expected_cols_pages", None)
        if isinstance(d, dict) and not self.vline_overrides:
            d.pop("vline_overrides", None)
        if isinstance(d, dict) and not self.hline_hints:
            d.pop("hline_hints", None)
        if isinstance(d, dict) and self.bend_w80_med is None:
            d.pop("bend_w80_med", None)
        return d


@register_step
class BorderDetectStep(Step):
    spec = StepSpec(
        id="border_detect", title="Step1 边框探测", version="1.20", unit="page",   # 1.20：上版框弱线护栏（seg/lines._weak_top_guard）：选中的线横向墨量不到带里最强横线的 0.3、上方 ≥0.021 页高处另有够强的横线，改取那条；横墨在带里峰最高的那档倾角上量（选中线倾角搜飞时不被它带偏，vol93 p18）（粗框条／双边框页上版框落到首行字顶，殿本全 99 册 16516 页只动 15 页：vol56 p43、vol63 p8、vol82 p217、vol93 p18、vol15 p151、vol38 p161 等，下游整页假抬头框、真抬头列判不出，或整列少切一格）；1.19：列宽重拟合第一遍拟不出时，墨投影减本页底色（20 分位）再扣墨、找空白，重拟一次（第一遍拟得出的页不变）：满页霉点／污渍的页字缝里也有墨，真线全被扣成负分、DP 无解（第 3 轮 vol43 p1 卷首页漏两条界行、只剩 8 列；pitch_rescue 2.1）；1.18：列宽重拟合换了线后，在新的一串直线上重拟合三段折线（`border.refit_bends`）；旧折线形状是在自由模式错的线网上拟的、护栏借形状把真线拗弯，殿本 r3 vol46 p78 左三条线下半段斜进字里；1.17：「横带按文字缝重定位」后的线，沿线压着细墨（界行）的行不许比直线少，少了不重定位（A20 11-03 报 vol84 p101/112、vol21 p68、vol40 p173：真界行直、单条线弯 20–30px 斜穿字；seg/polyline._hit_frac）；1.16：列宽均匀约束（doc/design/列宽均匀约束.md，Sheldon 11-03 定为强约束）：列距救援 7 路并成一路 `seg/columns.fit_columns`（候选：自由线、网格线、界行残段、淡界行细峰、字间空白中点、外推／补宽外框线，扣两侧墨后 DP 挑一串列宽全在带里的线）；带与 strict/loose/off 由册配置 `columns:` 定；出带的列打 flag `col_width_out_of_band`；1.15：列距救援三处放宽（殿本 r2 待审 S 类 4 页、90 格）：frame 路残段搜到外列宽进带为止（vol73 p110、vol94 p123 外框线挑在外列字心）；extend 路外推出图边截到图边（vol86 p151 折痕劈列、末列贴图边）；snap 路吸不动时按合格邻列列距推线再吸（vol44 p108 假线在字心、真界行断续）；1.14：列距救援加最后一路 pad：外列偏窄、外侧既没版框残段也没字（版框没印出来），外框线按中位列距外推（全唐文 07 p47、13 p141、11 p74、05 p160 首／末列被劈半）；前几路救得了的页结果不变；1.13：下版框次选峰在加宽的曲线上量（seg/lines.find_horizontal_border），不再取窗边截断峰；末行字身被当下框、整页丢末行的页（vol84 p89、vol85 p94 等 vol20–99 共 54 页）改对；1.12：三段折线加验收「折线沿线墨不许比直线多 0.08」，否则这条线退回直线（新图源界行淡，折点被字竖笔勾走、整页线中段平移进字里：vol70 p77、vol59 p58、vol24 p67、vol40 p34）；1.11：列距救援的网格路只护附近有界行残段的旧线（换图源 vol40 新 p1 卷首大印页，印泥里自由模式连挑三条字心线）；1.10：列距救援加第 4 路 snap：出带列两边的线吸到淡界行细峰／字间空白中点（vol24 p69、vol29 p28、vol37 p76、vol48 p121），网格线数比自由模式多也照收（vol45 p54）；1.9：列距救援加第 0 路「窄外列吸到外侧版框」，并不许任何一路把贴版框的旧外列甩出网（v0.5.17 首跑 vol40 p14、vol46 p118/p148：fuse 外推进版心条、整网平移一列丢真列）；1.8：fuse 的候选池加界行残段（竖墨线连续 ≥ 0.8 列宽，vol16 p8 全页小字雙行、界行只在天头那一截），外推外框线就近吸到残段上；1.7：列距救援第三条路 fuse（自由线＋网格线＋外推外框线拼一串等宽列，vol20 p113）；1.6：列距救援 pitch_rescue（缺省开，impl/keben/pitch_rescue）； 1.5：外框线也按横带证据回直线（border_geometry.snap_verticals_to_evidence）；1.4：抬头框字凸出判据（border_geometry._raised_text_top）；1.3：抬头块向邻列延伸（border_geometry._extend_head_raise）
        consumes=("raw_page",), produces=("borders", "line_index"), params=BorderDetectParams,
        code_deps=("open_guji_cv.impl.keben.border", "open_guji_cv.seg.polyline", "open_guji_cv.seg.frame_types", "open_guji_cv.seg.grid", "open_guji_cv.seg.lines",
                   "open_guji_cv.impl.keben.column_types", "open_guji_cv.impl.keben.column_pair_merge",
                   "open_guji_cv.impl.keben.pitch_rescue", "open_guji_cv.seg.columns"),
        # `leaf_layout` 决定要不要标版心（`margin`），改册配置必须让产物过期；
        # `column_grid` / `col_pitch` / `frame_height` / `vline_polyline` 决定竖线
        # 走哪条路、用哪组阈值，同理。
        # ⚠️ 2026-09-16 加 `frame_height` 时，**没有任何一本书写这个字段**（全 None），
        # 输出逐位不变，但指纹变了 → siku 504 页 + bxgb 55 页 Step1 连同下游一次性
        # 过期重跑。这是有意付的代价：漏声明的后果是「改了 yaml 产物还报新鲜」，
        # 那种静默错误比一次重跑贵得多（见「指纹不认册配置」那条教训）。
        book_deps=("leaf_layout", "expected_cols", "bottom_gap",
                   "top_band_frac", "bottom_band_frac", "column_grid", "col_pitch",
                   "frame_height", "vline_polyline", "outer_shift", "outer_gap",
                   "frame_layers", "columns"),
        # 纯函数：读原图算完直接返回，无实例级缓存、无数据库/模型一次性初始化，
        # `scripts/parallel_border_detect.py` 已验证页级并行与串行 sha256 逐位一致
        # （2026-09-17，见 doc/segmentation_v2_pipeline.md「Step 1 性能」）。
        parallel_safe=True,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: BorderDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        if not p.edge_strip:
            return self._run_page(ctx, page, None)
        gray = ctx.raw_page(page)
        stripped, cut_l, cut_r = strip_page_edge(gray, p.ink_threshold)
        if not (cut_l or cut_r):
            return self._run_page(ctx, page, None)
        # 抹了书口条的一版与原样一版都跑，挑出带列少的；一样多时挑穿字分低的（都在原图上量）。书口紧贴版框的页
        # 抹的时候会连版框线一起抹掉（脉经 02 p24），所以不能抹了就用。
        a = self._run_page(ctx, page, None)
        b = self._run_page(ctx, page, stripped)

        def _key(out):
            n_bad = sum(1 for ln in out["line_index"].lines if any(f.startswith(COL_WIDTH_FLAG) for f in ln.flags))
            return n_bad, round(gutter_ink_score(out["borders"].to_result(), gray, p.ink_threshold), 2)
        if _key(b) < _key(a):
            for ln in b["line_index"].lines:
                ln.flags.append(f"edge_strip：探竖线前抹掉页边书口条（左 {cut_l}px、右 {cut_r}px）")
            return b
        return a

    def _run_page(self, ctx: RunContext, page: int, gray_det) -> dict[str, BaseModel]:
        """`gray_det`：给 `detect_borders` 用的图（`edge_strip` 抹过书口条的那张）；None＝原图。"""
        p: BorderDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        cols = p.expected_cols_pages.get(page) or p.expected_cols or ctx.book.expected_cols
        gray = ctx.raw_page(page)
        if gray_det is None:
            gray_det = gray
        H, W = gray.shape[:2]
        grid = ctx.book.column_grid
        col_pitch = ctx.book.col_pitch
        grid_page = bool(p.column_grid_pages) and page in set(_expand_pages(p.column_grid_pages))
        if grid_page:
            grid = True
            col_pitch = p.grid_col_pitch if p.grid_col_pitch is not None else col_pitch
        # 缺省关时不传这个参数（border_geometry 的缺省就是关），与加字段前的调用一模一样
        lattice_kw = {"grid_lattice_fallback": True} if (grid_page and p.grid_lattice_fallback) else {}
        # 弯页门槛：给了才传（缺省＝代码常数，与加字段前的调用一模一样）
        bend_kw = {"bend_w80_med": p.bend_w80_med} if p.bend_w80_med is not None else {}
        # 页级人给版框位置：本页写了才传
        hint = p.hline_hints.get(page) or {}
        bad = set(hint) - {"top", "bottom"}
        if bad:
            raise ValueError(f"border_detect.hline_hints.{page} 只认 top／bottom，多了 {sorted(bad)}")
        hint_kw = {f"{k}_hint": float(v) for k, v in hint.items() if v is not None}
        # `bottom_gap` 给了才启用下版框跨页先验救援；没给就是加这套机制之前的
        # 行为（缺省参数逐位不变）。标定方法见 BookSpec.bottom_gap 的注释。
        def _detect(n_cols: int, grid: bool = grid, col_pitch=col_pitch):
            return detect_borders(gray_det, expected_cols=n_cols, ink_threshold=p.ink_threshold,
                                  book_bottom_gap=ctx.book.bottom_gap,
                                  top_band_frac=ctx.book.top_band_frac,
                                  bottom_band_frac=ctx.book.bottom_band_frac,
                                  column_grid=grid,
                                  col_pitch=col_pitch,
                                  frame_height=ctx.book.frame_height,
                                  outer_shift=ctx.book.outer_shift,
                                  book_outer_gap=ctx.book.outer_gap,
                                  frame_layers=ctx.book.frame_layers,
                                  vline_polyline=ctx.book.vline_polyline,
                                  head_raise_scale=p.head_raise_scale,
                                  top_weak_ratio=p.top_weak_ratio, top_weak_floor=p.top_weak_floor,
                                  **({"bottom_weak_ratio": p.bottom_weak_ratio} if p.bottom_weak_ratio else {}),
                                  **({"bottom_lock_reslope": True} if p.bottom_lock_reslope else {}),
                                  **({"top_edge_reslope": True} if p.top_edge_reslope else {}),
                                  **hint_kw, **lattice_kw, **bend_kw)

        res = _detect(cols)
        if grid_page:
            pad_outer_columns(res)
        if grid and p.grid_outer_trim and not p.grid_outer_fix:
            trim_outer_columns(res, gray, p.grid_outer_trim, n_cols=cols, ink_threshold=p.ink_threshold,
                               col_pitch=col_pitch, frame_height=ctx.book.frame_height)
        rescued = None
        col_spec = ColumnSpec.from_dict(ctx.book.columns)

        def _rescue(r, force: bool = False):
            # 网格模式必须带列距先验（见 border_geometry.detect_borders）；书上没写就取本页自由模式的中位列距
            # force（grid_outer_fix）：按版式列数拟、不查旧线护栏（见 pitch_rescue.rescue）
            kw = {"n_lines": cols + 1, "keep_guard": False} if force and cols else {}
            r, how = pitch_rescue(r, gray, lambda pitch: _detect(cols, True, col_pitch or pitch),
                                  leaf_layout=ctx.book.leaf_layout, ink_threshold=p.ink_threshold,
                                  spec=col_spec, **kw)
            if how:
                # 换了线就在新的一串直线上重拟合折线（旧形状是在错的线网上拟的，vol46 p78）
                r = refit_bends(r, gray, ink_threshold=p.ink_threshold,
                                vline_polyline=ctx.book.vline_polyline, **bend_kw)
            return r, how

        if p.pitch_rescue and not grid:
            res, rescued = _rescue(res)
        free_switched = None
        if grid and not grid_page and p.grid_free_fallback:
            s_grid = gutter_ink_score(res, gray, p.ink_threshold)
            if s_grid > p.grid_free_fallback:
                alt = _detect(cols, False)
                how = None
                if p.pitch_rescue:
                    alt, how = _rescue(alt)
                s_free = gutter_ink_score(alt, gray, p.ink_threshold)
                if len(alt.verticals) == len(res.verticals) and s_free < GRID_FREE_RATIO * s_grid:
                    res, rescued = alt, how
                    free_switched = f"穿字分 {s_grid:.2f}→{s_free:.2f}"
        outer_fixed = None
        if grid and not grid_page and p.grid_outer_fix:
            import copy

            def _outer(r):
                ns = fix_outer_sliver(r, gray, n_cols=cols, ink_threshold=p.ink_threshold)
                nt = (trim_outer_columns(r, gray, p.grid_outer_trim, n_cols=cols, ink_threshold=p.ink_threshold,
                                         col_pitch=col_pitch, frame_height=ctx.book.frame_height, gap_only=True)
                      if p.grid_outer_trim else 0)
                return ns, nt

            def _n_bad(r):
                # 与下面列宽检查同一口径：x 取版框中高处
                ty = float(r.top.y_at(0.0)) if r.top is not None else 0.0
                by = float(r.bottom.y_at(0.0)) if r.bottom is not None else float(H - 1)
                xs_ = [float(v.x_at((ty + by) / 2.0)) for v in r.verticals]
                skip = {c.col for c in classify_columns(xs_, leaf_layout=ctx.book.leaf_layout) if c.kind != "body"}
                chk_ = check_columns(xs_, col_spec, skip=skip)
                return len(chk_.bad) if chk_.judged else 0

            # A：只重定外框线。B：先按版式列数强拟列宽均匀（列宽均匀是强约束；网格模式原先不跑），再重定外框线。
            # 拟合的外列带宽到 1.3 倍，书口条会被圈回来、内线跟着挪（02 p24），所以 A 已经全在带里就用 A；
            # 否则 B 出带的列更少才用 B。
            a = copy.deepcopy(res)
            n_sliver, n_trim = _outer(a)
            pick, how_b = a, None
            if p.pitch_rescue and _n_bad(a):
                b, how_b = _rescue(copy.deepcopy(res), force=True)
                if how_b:
                    ns_b, nt_b = _outer(b)
                    if _n_bad(b) < _n_bad(a):
                        pick, n_sliver, n_trim, rescued = b, ns_b, nt_b, how_b
            res = pick
            if n_sliver or n_trim:
                outer_fixed = f"去窄条补对侧版框 {n_sliver} 处、收外框线 {n_trim} 条"
        if page in p.vline_overrides:
            _apply_vline_override(res, p.vline_overrides[page])
        # 人裁逐列抬头（`lookup.resolved_head_raise`）：补 Step1 漏认的抬头框／去掉认错的。本页没有裁决时不动
        from ..feedback.lookup import resolved_head_raise
        hr_verdicts = {c: n for (pg, c), n in resolved_head_raise(ctx.book.id).items() if pg == page}
        hr_done = apply_head_raise_verdicts(res, hr_verdicts, ctx.book.chars_per_line or 21,
                                            p.head_raise_scale) if hr_verdicts else {}
        borders = Borders.from_result(res, cols)

        # 列类型：`borders.verticals` 已是右上原点空间、x 升序（右→左），与
        # `line_index` 同一坐标空间，不需要翻转。y 取版框上下沿（列位是整列的，
        # 不逐列量墨——那是 Step2/3 的事）。
        top_y = float(res.top.y_at(0.0)) if res.top is not None else 0.0
        bot_y = float(res.bottom.y_at(0.0)) if res.bottom is not None else float(H - 1)
        # x 在版框**中高**处取，不取 `x_at_top`（y=0 处）：界行有斜率时 y=0 离版框
        # 顶还有三百多行，整排列框会偏几十 px（vol02 p149 偏 40px，叠图上绿框离开
        # 界行、像是界行错了）。列宽/列类型也该按版框里的 x 算。
        y_mid = (top_y + bot_y) / 2.0
        xs = [float(v.x_at(y_mid)) for v in res.verticals]      # VLine（记录 VLineRec 没有 x_at）
        filled = list(res.vline_filled) or [False] * len(xs)
        # 列宽检查（strict／loose 都做，同交接闸口径）：出带的列打 flag，交接闸据此标页
        col_chk = (check_columns(xs, col_spec, skip={c.col for c in classify_columns(xs, leaf_layout=ctx.book.leaf_layout)
                                                     if c.kind != "body"})
                   if col_spec.uniform != "off" else None)
        lines = []
        for c in classify_columns(xs, leaf_layout=ctx.book.leaf_layout):
            flags = [c.reason] if c.reason else []
            # 列位 col（1 起）夹在 xs[col-1] 与 xs[col] 之间；任一侧是插值线就标出来
            if filled[c.col - 1] or filled[c.col]:
                flags.append("rule_interpolated")
            if c.col in hr_done:
                flags.append(f"head_raise_verdict：人裁抬头 {hr_done[c.col]} 格，Step1 的抬头框已按裁决"
                             + ("补上" if hr_done[c.col] else "去掉"))
            if outer_fixed:
                flags.append(f"grid_outer_fix：外框线已重定（{outer_fixed}）")
            if free_switched:
                flags.append(f"grid_free_fallback：网格模式补出的竖线穿字，改用自由模式的线（{free_switched}）")
            if rescued:
                flags.append(f"pitch_rescued：页上有列宽出带（假竖线、外列落在网外或被劈半），已按列宽均匀重拟合（{rescued}）")
            if col_chk is not None and col_chk.judged and c.col in col_chk.bad:
                flags.append(f"{COL_WIDTH_FLAG}：列宽 {col_chk.ratios[c.col - 1]:.2f} 倍列距，出了带")
            lines.append(LineRec(col=c.col, kind=c.kind, x0=c.x0, x1=c.x1, y0=top_y, y1=bot_y,
                                 width=c.width, flags=flags))
        n_body = sum(1 for ln in lines if ln.kind == "body")
        return {
            "borders": borders,
            "line_index": LineIndex(page=page, width=W, height=H, em=None,
                                    pitch=None, n_body=n_body, lines=lines),
        }
