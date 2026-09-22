# -*- coding: utf-8 -*-
"""Step1/Step2 边框类裁决的卡片装配——从 artifact 迁进控制台。

用户 2026-09-11 定：「以后完全不走 artifact，都走控制台」。这四类裁决原先由
`scripts/build_border_gold_reviews.py`（cols / head / outer）与
`scripts/build_column_border_review.py`（colborder）生成一次性 Artifact 网页，
标注后靠脚本导出金标。搬进控制台后不再现算/现抽样——**直接读已经跑出来的
`borders` / `column_windows` 产物**，卡片就是"这一页/这一列现在的探测结果"，
跟控制台其余叠图口径一致（数值长期、图像即算）。

裁决落地不变：写 `/api/events`（kind=`verdict` 给 cols/head/outer，
`border_class` 给 colborder），路由表已有映射（`feedback/routes.py`），
不新增消费者。

卡片 id 规则（喂给 `feedback/harvest.parse_card_id`）：
    cols:{book}:{page}            outer:{book}:{page}:{top|bottom}
    head:{book}:{page}            colborder:{book}:{page}:{col}:{top|bot}
    pageline:{book}:{page}        下版框整页坐标金标（overview 2026-09-12 下发）
    headcol:{book}:{page}:{col}   列级抬头精标（overview 2026-09-12 下发）

⚠️ `headcol` 的前缀**不能带连字符**（写成 `head-col` 解析不出来）：
`harvest._ID_PATTERNS` 的前缀段是 `[a-z_]+`，解析不出 book/page/col 就只
剩一个 key，金标的 anchor 会整个塌掉。

`pageline` 卡只出下端（`01-下版框根修先造金标.md` 只要下版框）：整页
通栏宽带（原图按现役下版框线位置裁一条横跨全宽的带），一页拖一条线
（保留现役斜率，只调整整体偏移），一眼能看出哪条才是贯穿全页的印刷
直线。线两端各自可拖（现役斜率本身也可能探错，只给整体平移改不了
斜率）。落 `border-detection/bottom-offset`，字段是 `y_left`/`y_right`
（通栏带裁剪图坐标，两点定线自带斜率）+ `verdict`。

（原先还有个逐列裁剪图标注 `linebot`，窄列裁剪图里版框墨条常与相邻字缝
糊在一起分不清，标注系统性偏向"字开始的地方"而非墨条本身，且这类误判
整页一致——不是列级噪声，说明窄裁剪图本身就不该拿来标这个。已用上面的
`pageline` 取代，2026-09-12 删除，标注结果一并作废。）
"""

from __future__ import annotations

import cv2
import numpy as np

from ..core.book import load_book
from ..core.spec import page_key
from ..core.step import RunContext
from ..errors import ImageMissing, ProductMissing
from ..products.store import ProductStore
from ..utils.column_projection import (
    column_row_profile,
    column_text_band,
    denoise_column,
    page_column_windows,
    strip_column_rules,
)
from ..utils.preclean import effective_raw_path
from ..utils.image_io import imread as cv_imread, imwrite as cv_imwrite

HEAD_UP, HEAD_DN = 250, 45
STRIP_W, STRIP_PAD = 480, 42
CROP_ROWS = 220


def _borders(store: ProductStore, book: str, page: int):
    d = store.read(book, "border_detect", page_key(page), "borders")
    return d.to_result() if d else None


def _read_gray(book: str, page: int):
    """底图走 `effective_raw_path`——登记过预清理且产物已生成的页，标注卡片
    必须看管线实际处理的那张图，不能悄悄换成原图（否则会出现"卡片上看着
    有反色带没修，实跑却是好的"这种两边对不上的假象，同 `render/overlay.py
    ::overlay` 2026-09-12 修过的那个坑）。"""
    b = load_book(book)
    p = effective_raw_path(b, page)
    if not p.exists():
        raise ImageMissing(f"原图缺失: {p}")
    img = cv_imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing(f"原图读不出来: {p}")
    return img


def _need_borders(store: ProductStore, book: str, page: int):
    res = _borders(store, book, page)
    if res is None:
        raise ProductMissing(f"没有 border_detect 产物: {book}/{page}")
    return res


def cols_cards(store: ProductStore, book: str, pages: list[int], page_w: int = 560) -> list[dict]:
    """列探测卡：整页缩图 + 界行叠加（复用 `render/overlay.py` 的画法与颜色）。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        out.append(dict(id=f"cols:{book}:{pg}", kind="cols", book=book, page=pg,
                        n_cols=len(res.verticals),
                        img=f"/api/border-review/img/{book}/{pg}.jpg?kind=cols&w={page_w}"))
    return out


def head_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """抬头有无卡：上版框横带原图，不叠任何探测结果（要量召回率）。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        out.append(dict(id=f"{book}:{pg}", kind="head", book=book, page=pg,
                        img=f"/api/border-review/img/{book}/{pg}.jpg?kind=head"))
    return out


HEADCOL_UP, HEADCOL_DN = 330, 400   # 列级抬头带：上版框之上/之下各取多少（原图像素）
HEADCOL_SIDE = 18                   # 左右各多带一点邻列，便于跟相邻列比高低

# ── 卡片上的两个标记：`detected`（权威）与 `suspect`（线索）──────────
#
# **`detected` 才是抬头判据**：Step1 `detect_head_raise` 的输出——水平投影找
# 内/外边框 + 墙线校验，18 列列级金标命中 15、零误报、inner_y 中位误差
# 0.55px（用户 2026-09-12：「要，它比较准」）。
#
# 下面这套「框上字墨行数」是**第二档线索**，不是判据：探测器没报、但框上
# 字墨很多的列 = 疑似漏检，优先人裁。两者不是包含关系——p11 c6
# 「御纂周易述義」、p136 c4「易傳三十卷」都是墨量报而 `head_raise` 漏的真例。
#
# 这个量的来历：2026-09-12 用户反馈「可疑的太多了，大部分都是普通列。应该是
# 在内边框上方特定高度有大量墨迹的才是（不包括外边框）」。更早一版判据在前端，
# 用「现役判非抬头 + 有 top_slack + 首格是字且 y0<30」——**一点墨都没量**，
# vol02 p1-59 就标出 7.1% 的列。
#
# 换成直接量墨。关键是"不包括外边框"这一条：**墨占比（frac）量不出来**，
# 实测普通页 vol02/46 各列 frac 0.184~0.207，反而**高于**真抬头页 p11 的
# 0.16~0.19——因为这条带里墨的大头是外边框那根粗横条，不是字。
# 所以按**行**数：一行墨占比在 (0.02, 0.6) 之间才算"字墨行"——
#   ≤0.02 是空白纸，≥0.6 是贯通全宽的横线（外边框/装饰线），两头都剔掉。
#
# vol02 全书 1664 列实测分布：中位 7、p90 15、p95 18、p99 27，然后直接跳到
# 最大 107。真抬头列（p11 c4/c5/c6 = 95/100/107）跟普通列之间是**断崖**，
# 不是连续过渡，所以阈值落在 40 很稳：
#   ≥30 → 13 列 (0.78%)   ≥40 → 8 列 (0.48%)   ≥50 → 7 列 (0.42%)
# 取 40，命中 vol02 的 p11(c4,c5,c6)、p101(c5,c6,c7)、p136(c4) 等，
# 目视复核 p101 c6 是「聖祖仁皇帝」、p136 c4 是「巽溪易傳」，都是真抬头。
HEADCOL_SUSPECT_ABOVE = 140    # 从内边框往上量多深（不要碰到外边框那条粗条）
HEADCOL_SUSPECT_MARGIN = 12    # 下沿离内边框留一点，避开边框自己的线宽
HEADCOL_SUSPECT_MIN_ROWS = 40  # 字墨行数达到这个数才算可疑
_ROW_INK_LO, _ROW_INK_HI = 0.02, 0.6


def _head_ink_rows(gray: np.ndarray, res, col: int, ink_threshold: int = 128) -> int:
    """内边框上方 `HEADCOL_SUSPECT_ABOVE` 像素内的**字墨行数**（剔除贯通横线）。"""
    h, w = gray.shape
    vs = res.verticals
    if col < 1 or col >= len(vs):
        return 0
    right_v, left_v = vs[col - 1], vs[col]
    btop = float(np.mean([res.top.y_at(v.x_at(0.0)) for v in (right_v, left_v)]))
    ym = btop - HEADCOL_SUSPECT_ABOVE / 2.0
    xs = [(w - 1) - v.x_at(ym) for v in (right_v, left_v)]
    # 两侧各内缩 6px：界行本身贯通整条带，算进来每行都带底噪
    xl, xr = int(max(0, min(xs))) + 6, int(min(w, max(xs))) - 6
    lo = max(0, int(btop - HEADCOL_SUSPECT_ABOVE))
    hi = max(lo + 5, int(btop - HEADCOL_SUSPECT_MARGIN))
    if xr - xl < 20:
        return 0
    band = (gray[lo:hi, xl:xr] < ink_threshold).astype(np.uint8)
    rows = band.sum(axis=1) / float(xr - xl)
    return int(((rows > _ROW_INK_LO) & (rows < _ROW_INK_HI)).sum())


def headcol_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """列级抬头精标卡：一列一张，上版框那一段的原图 **＋ 三层几何叠加**。

    页级 `head` 卡（整页横带）判「这页有没有抬头」，量的是 Step1 抬头框的
    召回率；这一级判**逐列**的三件事：是不是抬头、抬高几格、首字有没有被
    切掉。`n_raised` 至今没有逐列真值（页级参数 + 墨跨度 hint 两个来源都
    是估的），这张卡就是去补那个真值的。

    ⚠️ **这张卡默认叠线，跟页级 `head` 卡的口径相反**（用户 2026-09-12 定）。
    页级卡刻意不叠——那道题问「有没有」，卡上印了机器判断人就会顺着点，
    量出来的是机器自己。但列级这三问**不叠线根本答不了**：
    「抬高几格」要看得见格子切分线才数得出格数，「首字是否完整」要看得见
    版框线才知道字是不是被切在框外。所以这里叠三层：

    1. **整页上内边框**（`res.top`，蓝）——页级那条斜线在本列的位置；
    2. **本列识别的抬头内边框**（`win.head_raise_inner_y`，橙）——**探不到
       就不画**，卡片另发 `det_hr_inner=null` 让前端显式写「未探到」。
       不能让「没画线」和「线在 0」看起来一样。
    3. **格子切分线**（`cells` 的 `quad_page` 上沿，红）——逐格的实际切分
       位置，数线就能数格数。

    叠加可关（`overlay=0`），想看纯原图时用；但默认开，因为不叠的那版
    实测「无法判定几格、首字是否完整」（用户 2026-09-12 反馈）。

    坐标：`quad_page` 是**原图规范空间（右上原点）**的四角，直接减 `crop_top`
    就是裁剪图里的 y，不需要再走 `ColumnMapper` 逆映射（那条路是给没有
    `quad_page` 的老产物用的）。
    """
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        gate = store.read(book, "column_gate", page_key(pg), "gate_manifest")
        cells = store.read(book, "row_segment", page_key(pg), "cells")
        gcols = {c.col: c for c in (gate.columns if gate else [])}
        ccols = {c.col: c for c in (cells.columns if cells else [])}
        gray = _read_gray(book, pg)     # 量「内边框上方字墨行数」用，一页读一次
        for win in page_column_windows(res):
            gc, cc = gcols.get(win.col), ccols.get(win.col)
            # 首字是什么：给人一个「这列第一个字」的参照，好判断有没有被切掉
            first = None
            if cc is not None and cc.cells:
                head = sorted(cc.cells, key=lambda c: c.slot)[0]
                first = {"slot": head.slot, "kind": head.kind,
                         "y0": round(float(head.y0), 1)}
            ink_rows = _head_ink_rows(gray, res, win.col)
            # 「可疑」以 **Step1 抬头框探测**为准（2026-09-12 用户定：「要，它比较准」）。
            # 那是水平投影找内/外边框 + 墙线校验的正经判据，18 列列级金标
            # 命中 15 零误报、inner_y 中位误差 0.55px；框上字墨行数只是标注台
            # 临时凑的辅助量，**不是抬头判据**。
            #
            # 但两者**不是包含关系**，所以墨量那条保留成第二档线索而不是删掉：
            #   p11 c6「御纂周易述義」、p136 c4「易傳三十卷」——墨量报、
            #   `head_raise` 漏（前者与 c4/c5 同属一段敬语，只因它的「御」恰好
            #   落在版框线以下才没丢字）。这类正是**待人裁**的样本，标注台丢掉
            #   它就等于把探测器的漏检一起藏了，而这张卡的用处恰恰是量漏检。
            hr_cols = {b.col for b in res.head_raise}
            out.append(dict(
                id=f"{book}:{pg}:{win.col}", kind="headcol",
                book=book, page=pg, col=win.col,
                det_raised=bool(win.raised),
                det_n_raised=None if cc is None else int(cc.n_raised),
                det_top_slack=None if gc is None else round(float(gc.top_slack), 1),
                det_hr_inner=(None if win.head_raise_inner_y is None
                              else round(float(win.head_raise_inner_y), 1)),
                det_first_cell=first,
                ink_rows=ink_rows,
                # detected：Step1 探到抬头框（权威判据）
                # suspect：探测器没报、但框上字墨很多 → 疑似漏检，优先人裁
                detected=bool(win.col in hr_cols),
                suspect=bool(win.col not in hr_cols
                             and ink_rows >= HEADCOL_SUSPECT_MIN_ROWS),
                img=f"/api/border-review/img/{book}/{pg}.jpg?kind=headcol&col={win.col}"))
    return out


def outer_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """外框外延卡：上/下各一张，叠已存的外延偏移线。没探到外框的页不出卡。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        for side, off in (("top", res.top_outer_offset), ("bottom", res.bottom_outer_offset)):
            if off is None:
                continue
            out.append(dict(id=f"outer:{book}:{pg}:{side}", kind="outer", book=book, page=pg,
                            side=side, offset=round(float(off), 2),
                            img=f"/api/border-review/img/{book}/{pg}.jpg?kind=outer&side={side}"))
    return out


def colborder_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """单列矫正·上下版框核校卡：一列出两张（上端/下端），只记类别不记坐标。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        for win in page_column_windows(res):
            for end in ("top", "bot"):
                out.append(dict(
                    id=f"colborder:{book}:{pg}:{win.col}:{end}", kind="colborder",
                    book=book, page=pg, col=win.col, end=end, raised=win.raised,
                    img=(f"/api/border-review/img/{book}/{pg}.jpg"
                        f"?kind=colborder&col={win.col}&side={end}")))
    return out


# ── 图像装配（供 console/routers/border_review.py 的图像端点调用）──────

def render_cols_img(store: ProductStore, book: str, page: int, page_w: int = 560) -> np.ndarray:
    from ..render.overlay import draw_vline

    gray = _read_gray(book, page)
    res = _need_borders(store, book, page)
    h, w = gray.shape
    sc = page_w / w
    thumb = cv2.cvtColor(cv2.resize(gray, (page_w, int(h * sc)), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_GRAY2BGR)
    H2, W2 = thumb.shape[:2]
    for v in res.verticals:
        rec = dict(x_at_top=v.x_at_top * sc, slope=v.slope,
                  k2=None if v.k2 is None else v.k2, k3=v.k3,
                  y1=None if v.y1 is None else v.y1 * sc, y2=None if v.y2 is None else v.y2 * sc)
        draw_vline(thumb, rec, W2, H2, (0, 40, 235), thick=1)
    return thumb


def render_head_img(store: ProductStore, book: str, page: int, head_w: int = 900) -> np.ndarray:
    gray = _read_gray(book, page)
    res = _need_borders(store, book, page)
    h, w = gray.shape
    ytop = int(res.top.y_at((w - 1) - w // 2))
    lo, hi = max(0, ytop - HEAD_UP), min(h, ytop + HEAD_DN)
    vx = sorted((w - 1) - v.x_at(h / 2.0) for v in res.verticals)
    x0, x1 = int(vx[0]) - 30, int(vx[-1]) + 30
    band = gray[lo:hi, max(0, x0):min(w, x1)]
    return cv2.resize(band, (head_w, int(band.shape[0] * head_w / max(1, band.shape[1]))),
                      interpolation=cv2.INTER_AREA)


def render_headcol_img(store: ProductStore, book: str, page: int, col: int,
                        out_w: int = 300, overlay: bool = True) -> np.ndarray:
    """一列的上版框段原图 ＋ 三层几何叠加（见 `headcol_cards` 的说明）。

    坐标口径跟 `render_head_img` 一致：`VLine.x_at` / `HLine.y_at` 吃的是
    **右上原点规范空间**的 x，而 numpy 切片要左上原点的列号，两者用
    `x_tl = (w-1) - x_tr` 互换——这一步漏掉就会取到镜像位置的那一列。

    列号从右到左数（`page_column_windows` 的约定），所以 `verticals[col-1]`
    是这一列的右边框、`verticals[col]` 是左边框。

    `overlay=False` 回到纯原图。三层线的颜色固定（BGR）：
    蓝=整页上内边框、橙=本列抬头内边框、红=格子切分线。**线画在缩放之前**
    的裁剪图上，缩放用 `INTER_AREA` 会把 1px 线糊掉，所以线宽给 2。
    """
    gray = _read_gray(book, page)
    res = _need_borders(store, book, page)
    h, w = gray.shape
    vs = res.verticals
    if not 1 <= col < len(vs) + 1 or col >= len(vs):
        raise ProductMissing(f"没有这一列：{book}/{page} c{col}（共 {max(0, len(vs) - 1)} 列）")
    right_v, left_v = vs[col - 1], vs[col]
    ymid = h / 2.0
    x_right_tl = (w - 1) - right_v.x_at(ymid)
    x_left_tl = (w - 1) - left_v.x_at(ymid)
    x0 = int(min(x_left_tl, x_right_tl)) - HEADCOL_SIDE
    x1 = int(max(x_left_tl, x_right_tl)) + HEADCOL_SIDE
    x0, x1 = max(0, x0), min(w, x1)
    # 上版框在这一列中心处的 y（版框是斜的，取列中心而不是页面右端）
    xc_tr = (w - 1) - (x0 + x1) / 2.0
    ytop = int(res.top.y_at(xc_tr))
    lo, hi = max(0, ytop - HEADCOL_UP), min(h, ytop + HEADCOL_DN)
    band = gray[lo:hi, x0:x1]
    if band.size == 0:
        raise ProductMissing(f"列带裁出来是空的：{book}/{page} c{col}")

    img = cv2.cvtColor(band, cv2.COLOR_GRAY2BGR)
    if overlay:
        bw = img.shape[1]

        def hline(y_page: float, color, thick: int = 2, dash: bool = False) -> None:
            y = int(round(y_page)) - lo
            if not 0 <= y < img.shape[0]:
                return
            if not dash:
                cv2.line(img, (0, y), (bw - 1, y), color, thick)
                return
            for xs in range(0, bw, 14):
                cv2.line(img, (xs, y), (min(bw - 1, xs + 7), y), color, thick)

        # ① 整页上内边框（蓝）——这一列中心处的 y
        hline(res.top.y_at(xc_tr), (235, 120, 0))
        # ② 本列抬头内边框（橙虚线）；探不到就不画，卡片文字里写「未探到」
        win = next((x for x in page_column_windows(res) if x.col == col), None)
        if win is not None and win.head_raise_inner_y is not None:
            hline(win.head_raise_inner_y, (0, 150, 255), dash=True)
        # ③ 格子切分线（红）——quad_page 上沿，外加末格下沿
        cc = store.read(book, "row_segment", page_key(page), "cells")
        crec = next((c for c in cc.columns if c.col == col), None) if cc else None
        if crec is not None:
            ordered = sorted((c for c in crec.cells if c.quad_page), key=lambda z: z.slot)
            for cell in ordered:
                hline(min(p[1] for p in cell.quad_page), (60, 60, 220), thick=1)
            if ordered:
                hline(max(p[1] for p in ordered[-1].quad_page), (60, 60, 220), thick=1)

    sc = out_w / max(1, img.shape[1])
    return cv2.resize(img, (out_w, max(1, int(img.shape[0] * sc))),
                      interpolation=cv2.INTER_AREA)


def render_outer_img(store: ProductStore, book: str, page: int, side: str,
                     strip_w: int = STRIP_W, zoom: int = 2) -> np.ndarray:
    gray = _read_gray(book, page)
    res = _need_borders(store, book, page)
    h, w = gray.shape
    L = res.top if side == "top" else res.bottom
    sign = -1.0 if side == "top" else 1.0
    off = res.top_outer_offset if side == "top" else res.bottom_outer_offset
    vx = sorted((w - 1) - v.x_at(h / 2.0) for v in res.verticals)
    cx = (int(vx[0]) + int(vx[-1])) // 2 - strip_w // 2
    cx = max(0, min(w - strip_w, cx))
    ymid = L.y_at((w - 1) - (cx + strip_w // 2))
    e = float(off) * sign if off is not None else 0.0
    top_y = max(0, int(ymid + min(0, e) - STRIP_PAD))
    bot_y = min(h, int(ymid + max(0, e) + STRIP_PAD))
    strip = cv2.cvtColor(gray[top_y:bot_y, cx:cx + strip_w], cv2.COLOR_GRAY2BGR)
    if off is not None:
        for i in range(strip_w):
            if (i // 11) % 2:
                continue
            y = int(round(L.y_at((w - 1) - (cx + i)) + e)) - top_y
            if 0 <= y < strip.shape[0]:
                strip[y, i] = (0, 40, 235)
    return cv2.resize(strip, (strip_w * zoom, strip.shape[0] * zoom), interpolation=cv2.INTER_NEAREST)


def render_colborder_img(ctx: RunContext, book: str, page: int, col: int, end: str
                         ) -> tuple[np.ndarray, list[float]]:
    """返回 (裁剪灰度图, 沿水平方向投影 0~1 列表)。顺序固化：定带 → 抹侧 → 只在带内算投影。"""
    from ..core.spec import column_key

    try:
        path = ctx.materialize("column_image", column_key(page, col))
    except Exception as e:   # noqa: BLE001
        raise ImageMissing(f"列图算不出来: {e}") from e
    img = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("列图读不出来")
    denoised = denoise_column(img)
    band = column_text_band(denoised)
    no_rules = strip_column_rules(denoised)
    core = no_rules[:, band[0]:band[1]]
    prof = column_row_profile(no_rules, band)
    h = core.shape[0]
    if end == "top":
        crop, pslice = core[:CROP_ROWS], prof[:CROP_ROWS]
    else:
        crop, pslice = core[h - CROP_ROWS:][::-1], prof[h - CROP_ROWS:][::-1]
    return crop, [float(v) for v in pslice]


PAGE_BAND_MARGIN = 260  # 通栏带在线两端各留多少像素做视觉参照（够看清有没有贴墨条）


def page_bottom_cards(store: ProductStore, book: str, pages: list[int]) -> list[dict]:
    """整页下版框偏移金标卡：一页一张，带现役线在通栏带坐标里的两端点。"""
    out = []
    for pg in pages:
        res = _borders(store, book, pg)
        if res is None:
            continue
        gray = _read_gray(book, pg)
        h, w = gray.shape
        bottom = res.bottom
        y_right = bottom.y_at_right          # 原图坐标，x_tl = w-1 处
        y_left = bottom.y_at_right + bottom.slope * (w - 1)  # x_tl = 0 处
        crop_top = max(0.0, min(y_left, y_right) - PAGE_BAND_MARGIN)
        crop_bottom = min(float(h), max(y_left, y_right) + PAGE_BAND_MARGIN)
        # ⚠️ 坐标只能以**原图**为准，不能以裁剪带为准（用户 2026-09-13 定）。
        # 原先只发相对 crop_top 的坐标，而 crop_top 是算法输出算出来的——
        # 算法一改，历史金标的绝对位置就整体漂移。vol02/161 实测偏了 83.2px：
        # 标注之后加了 `_fix_wild_angle` 角度护栏，恰好改动了这一页的下版框，
        # crop_top 跟着变，人标对的线被换算到了纯白处。同一个坑在 09-12 那批
        # 已经栽过一次（当时是"标注后 30 分钟有人改了代码"）。
        # 所以这里**同时发绝对坐标**，前端回写事件时存绝对值，金标自带参照系。
        out.append(dict(
            id=f"{book}:{pg}", kind="pageline", book=book, page=pg,
            page_w=w, page_h=h, crop_top=round(crop_top, 1),
            y_left=round(y_left - crop_top, 2), y_right=round(y_right - crop_top, 2),
            y_left_abs=round(y_left, 2), y_right_abs=round(y_right, 2),
            img=f"/api/border-review/img/{book}/{pg}.jpg?kind=pageline"))
    return out


def render_pageline_img(store: ProductStore, book: str, page: int) -> np.ndarray:
    """整页下版框通栏带：原图按现役线位置裁一条横带，不烧线——线由前端叠加、
    人可拖，图只给像素上下文。"""
    res = _need_borders(store, book, page)
    gray = _read_gray(book, page)
    h, w = gray.shape
    bottom = res.bottom
    y_right = bottom.y_at_right
    y_left = bottom.y_at_right + bottom.slope * (w - 1)
    crop_top = int(max(0.0, min(y_left, y_right) - PAGE_BAND_MARGIN))
    crop_bottom = int(min(float(h), max(y_left, y_right) + PAGE_BAND_MARGIN))
    return gray[crop_top:crop_bottom]
