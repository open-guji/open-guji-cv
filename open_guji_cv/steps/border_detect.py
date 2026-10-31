"""Step1 边框探测：原图 → 版框（上下内外）+ 界行（含三段折线）+ 抬头框 + 列类型。

包的是 `utils/border_geometry.detect_borders`，输入直接是**原始扫描**（不经 s1..s6），
输出坐标天然是右上原点规范空间。

另产 `line_index`（与现代链 `line_detect` **同一种产物**）：逐列位记类型
`body | margin | edge`，下游据此把非正文列排除在外。筒子页（`leaf_layout: folio`）
的版心就是靠它标成 `margin` 的——判据与两条负结果见 `books/siku_zongmu/column_types.py`。
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
from ..books.siku_zongmu.border import detect_borders
from ..books.siku_zongmu.column_pair_merge import PAIR_MERGED_FLAG, merge_narrow_pair
from ..books.siku_zongmu.column_types import classify_columns
from ..books.siku_zongmu.pitch_rescue import rescue as pitch_rescue

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


def apply_head_raise_verdicts(res, verdicts: dict[int, int], n_rows: int, scale: float = 1.0) -> dict[int, int]:
    """人裁逐列抬头（`lookup.resolved_head_raise`，本页 `col → n_raised`）改写 `res.head_raise`，返回改了的列。

    判 0 的列去掉 Step1 认的抬头框；判 n ≥ 1 而 Step1 没认的列补一个 `estimated` 抬头框。补的框高：本页有
    Step1 认下的抬头列就取它们离主上版框的中位距离（同页抬头框一样高），没有就取一格高（版框高 / `n_rows`）；
    多抬一级多加一格。内外框间距同理取本页中位，没有就按内框往上 `HR_DEFAULT_PAIR_GAP`（乘本册 `head_raise_scale`）。
    Step1 已认的抬头列不动（框是量出来的，比估的准）。"""
    from statistics import median

    from ..books.siku_zongmu.border import HR_DEFAULT_PAIR_GAP
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


class BorderDetectParams(BaseModel):
    expected_cols: int | None = Field(default=None, description="列数先验；None = 用 Book 的 expected_cols")
    ink_threshold: int = 128
    merge_narrow_pair: bool = False
    """窄对合并（`books/siku_zongmu/column_pair_merge`，overview GUJI-155）：相邻两条**内部**窄列、宽度和≈一列时，
    用 `expected_cols−1` 重探，接受条件见该模块。**缺省关**（要不要让各册 Step1 重算由 Morgan 定）；
    关着、或页上没有窄对时，产物逐字节不变。触发页的 `expected_cols` 记成少一列，闸读它。"""

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
    pitch_rescue: bool = True
    """列距救援（`books/siku_zongmu/pitch_rescue`，2026-10-23 sheldon 定缺省开）：自由模式探出的页上有一条列
    < 0.7 × 中位列宽（多挑了假竖线、外侧一整列落到网外）时，先用网格模式重探，选不出版框对再
    「去掉劈开窄对的线、在有字的一侧补外框线」，再不成就从自由线、网格线、外推外框线里拼一串等宽列（fuse）；
    新列网干净才接受。没触发的页逐字节不变。"""

    head_raise_scale: float = 1.0
    """抬头框探测的像素尺度（`border_geometry.HR_SCALE_LENGTHS`，2026-10-26，GUJI-748）：本册图相对殿本旧图
    的缩放比。那组长度常数是在旧图上量的绝对像素，换图源 siku-qiefen-v2（约 0.70 倍）后抬头框整片认不出
    （vol07 新 p43 五列抬头全丢）。换源的册与 `bottom_gap`、`period_prior` 乘同一个缩放比，如
    `params: {border_detect: {head_raise_scale: 0.7021}}`。缺省 1.0 不进参数 dump，产物与加字段前逐字节相同。"""

    @model_serializer(mode="wrap")
    def _drop_off_merge(self, handler):
        """缺省关时不进 dump：没开的书 `params_hash` 与加这个字段之前逐位相同。"""
        d = handler(self)
        if isinstance(d, dict) and not self.merge_narrow_pair:
            d.pop("merge_narrow_pair", None)
        if isinstance(d, dict) and not self.column_grid_pages:
            d.pop("column_grid_pages", None)
            d.pop("grid_col_pitch", None)
        if isinstance(d, dict) and not self.grid_lattice_fallback:
            d.pop("grid_lattice_fallback", None)
        if isinstance(d, dict) and self.head_raise_scale == 1.0:
            d.pop("head_raise_scale", None)
        return d


@register_step
class BorderDetectStep(Step):
    spec = StepSpec(
        id="border_detect", title="Step1 边框探测", version="1.13", unit="page",   # 1.13：下版框次选峰在加宽的曲线上量（seg/lines.find_horizontal_border），不再取窗边截断峰；末行字身被当下框、整页丢末行的页（vol84 p89、vol85 p94 等 vol20–99 共 54 页）改对；1.12：三段折线加验收「折线沿线墨不许比直线多 0.08」，否则这条线退回直线（新图源界行淡，折点被字竖笔勾走、整页线中段平移进字里：vol70 p77、vol59 p58、vol24 p67、vol40 p34）；1.11：列距救援的网格路只护附近有界行残段的旧线（换图源 vol40 新 p1 卷首大印页，印泥里自由模式连挑三条字心线）；1.10：列距救援加第 4 路 snap：出带列两边的线吸到淡界行细峰／字间空白中点（vol24 p69、vol29 p28、vol37 p76、vol48 p121），网格线数比自由模式多也照收（vol45 p54）；1.9：列距救援加第 0 路「窄外列吸到外侧版框」，并不许任何一路把贴版框的旧外列甩出网（v0.5.17 首跑 vol40 p14、vol46 p118/p148：fuse 外推进版心条、整网平移一列丢真列）；1.8：fuse 的候选池加界行残段（竖墨线连续 ≥ 0.8 列宽，vol16 p8 全页小字雙行、界行只在天头那一截），外推外框线就近吸到残段上；1.7：列距救援第三条路 fuse（自由线＋网格线＋外推外框线拼一串等宽列，vol20 p113）；1.6：列距救援 pitch_rescue（缺省开，books/siku_zongmu/pitch_rescue）； 1.5：外框线也按横带证据回直线（border_geometry.snap_verticals_to_evidence）；1.4：抬头框字凸出判据（border_geometry._raised_text_top）；1.3：抬头块向邻列延伸（border_geometry._extend_head_raise）
        consumes=("raw_page",), produces=("borders", "line_index"), params=BorderDetectParams,
        code_deps=("open_guji_cv.books.siku_zongmu.border", "open_guji_cv.seg.polyline", "open_guji_cv.seg.frame_types", "open_guji_cv.seg.grid", "open_guji_cv.seg.lines",
                   "open_guji_cv.books.siku_zongmu.column_types", "open_guji_cv.books.siku_zongmu.column_pair_merge",
                   "open_guji_cv.books.siku_zongmu.pitch_rescue"),
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
                   "frame_layers"),
        # 纯函数：读原图算完直接返回，无实例级缓存、无数据库/模型一次性初始化，
        # `scripts/parallel_border_detect.py` 已验证页级并行与串行 sha256 逐位一致
        # （2026-09-17，见 doc/segmentation_v2_pipeline.md「Step 1 性能」）。
        parallel_safe=True,
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: BorderDetectParams = ctx.params_for(self)  # type: ignore[assignment]
        cols = p.expected_cols or ctx.book.expected_cols
        gray = ctx.raw_page(page)
        H, W = gray.shape[:2]
        grid = ctx.book.column_grid
        col_pitch = ctx.book.col_pitch
        grid_page = bool(p.column_grid_pages) and page in set(_expand_pages(p.column_grid_pages))
        if grid_page:
            grid = True
            col_pitch = p.grid_col_pitch if p.grid_col_pitch is not None else col_pitch
        # 缺省关时不传这个参数（border_geometry 的缺省就是关），与加字段前的调用一模一样
        lattice_kw = {"grid_lattice_fallback": True} if (grid_page and p.grid_lattice_fallback) else {}
        # `bottom_gap` 给了才启用下版框跨页先验救援；没给就是加这套机制之前的
        # 行为（缺省参数逐位不变）。标定方法见 BookSpec.bottom_gap 的注释。
        def _detect(n_cols: int, grid: bool = grid, col_pitch=col_pitch):
            return detect_borders(gray, expected_cols=n_cols, ink_threshold=p.ink_threshold,
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
                                  **lattice_kw)

        res = _detect(cols)
        if grid_page:
            pad_outer_columns(res)
        rescued = None
        if p.pitch_rescue and not grid:
            # 网格模式必须带列距先验（见 border_geometry.detect_borders）；书上没写就取本页自由模式的中位列距
            res, rescued = pitch_rescue(res, gray, lambda pitch: _detect(cols, True, col_pitch or pitch),
                                        leaf_layout=ctx.book.leaf_layout, ink_threshold=p.ink_threshold)
        # 窄对合并（缺省关）：内部相邻两条窄列、宽度和≈一列 → 多了一条竖线，用 cols−1 重探。
        # 没触发／重探不被接受时原样返回，下面的产物逐字节不变。
        merged_col = None
        if p.merge_narrow_pair:
            res, cols, merged_col = merge_narrow_pair(res, cols, _detect,
                                                      leaf_layout=ctx.book.leaf_layout)
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
        lines = []
        for c in classify_columns(xs, leaf_layout=ctx.book.leaf_layout):
            flags = [c.reason] if c.reason else []
            if merged_col is not None and c.col == merged_col:
                flags.append(f"{PAIR_MERGED_FLAG}：原相邻两条窄列（宽度和≈一列）被多余竖线劈开，"
                             f"已用 {cols} 列重探去掉那条线")
            # 列位 col（1 起）夹在 xs[col-1] 与 xs[col] 之间；任一侧是插值线就标出来
            if filled[c.col - 1] or filled[c.col]:
                flags.append("rule_interpolated")
            if c.col in hr_done:
                flags.append(f"head_raise_verdict：人裁抬头 {hr_done[c.col]} 格，Step1 的抬头框已按裁决"
                             + ("补上" if hr_done[c.col] else "去掉"))
            if rescued:
                flags.append(f"pitch_rescued：页上有窄列（多挑假竖线、外侧整列落在网外），已按列距重定（{rescued}）")
            lines.append(LineRec(col=c.col, kind=c.kind, x0=c.x0, x1=c.x1, y0=top_y, y1=bot_y,
                                 width=c.width, flags=flags))
        n_body = sum(1 for ln in lines if ln.kind == "body")
        return {
            "borders": borders,
            "line_index": LineIndex(page=page, width=W, height=H, em=None,
                                    pitch=None, n_body=n_body, lines=lines),
        }
