# -*- coding: utf-8 -*-
"""现代印刷体的行（列）探测：无版框界行的页 → 正文列的窗口 + 各列类型。

刻本链的 Step1（`border_geometry.detect_borders`）找的是**墨线**：版框与界行。
现代排印本没有这些线，列与列之间只是纸；这里找的是**墨柱**：沿列方向投影，
墨段就是列，段间空白就是列距。三模式方案（overview `图片初步数字化/进度/总览/
05-三模式管线方案.md`）里叫 `line_detect`，"line" 是通用说法——竖排时一"行"就是一列。
本模块只处理竖排（`writing_mode=vertical-rl`）；横排按方案 §三在原图入口旋转 90°
后也走这里，尚未接入。

判据（北行日錄 40 页实测，600dpi、字身 ≈103px、列距 185.5px）：

- **列**：列方向投影 `colfrac > col_ink_min` 的连续段，宽 ≥ 0.15 em 才算（去噪点）；
- **字身 em**：所有段里最宽那一族的宽度中位数（宽 ≥ 0.5 × 最宽段的段）；
- **正文列**：0.75 em ≤ 宽 ≤ 1.35 em；更窄的是**小字列**，更宽的是**并列/粘连**
  （两列间隙被污渍连上），标 `wide`；
- **小字列**分几种去处：两条相邻窄段拼起来一个字身宽 → **双行小注整列**（一个列位，标
  `jiazhu_pair`）；贴着某正文列（间隙 ≤ 0.3 em）且 y 范围落在它里面 → **双行小注的一个子列**，
  并回该正文列（卷题「北行日録上」下的小注就是这样：右子列与大字连成一段，左子列自成一条
  窄段）；在一条**长竖线**（≥ 0.5 页高、墨占比 ≥ 0.5）外侧、或离正文块超过 `margin_gap_frac`
  × 列距 → **书口小字**（书名/页码）`margin`；块内够长（≥ 0.4 块高）的窄段 → **小字整列**
  （脚注列、单行小注整列，占一个列位、校對本里也是一行，标 `small_col`）；其余短的 → `footnote`；
- **空列位**：卷题页列与列之间空着整数个列位（「攻媿先生文集卷第一百十九」与「四明樓鑰大防」
  之间空一列）。相邻正文列中心距 ≈ k × 列距（k ≥ 2）时补 k−1 个 `empty` 列位——否则两列
  共用一条中线，窗口宽出一倍，闸2 的列宽一致性判据（L1c）会把卷题页的列全拒掉；
- **长横线 / 长竖线**先抹掉再投影，否则栏线本身会被当成一列。

产出直接落成刻本链同一种 `borders`（虚拟界行 = 相邻列位的中线，最外两条在块边之外
半个列间空白处；上下框 = 正文块的上下沿外扩 `pad_frac × em`）——下游 Step2
`column_crop`/`column_warp` 拿它算列窗口，一行不用改。**这里的界行是虚的**，别拿它当真墨线去量。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .border_geometry import BorderDetectionResult, HLine, VLine

LINE_KINDS = ("body", "empty", "footnote", "margin", "wide", "noise")


@dataclass
class LineRun:
    x0: int              # 左上原点像素坐标，半开 [x0, x1)
    x1: int
    y0: int              # 该列墨的 y 范围（含）；empty 列位取正文块的
    y1: int
    width: int
    kind: str = "body"
    col: int | None = None   # 列位号（body / empty），右→左从 1；其他 None
    flags: list[str] = field(default_factory=list)
    row_ink: float = 0.0     # 段内有墨的行占其 y 跨度的比例：文字列 0.6～0.85，竖线 ≈ 1

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclass
class LineLayout:
    width: int
    height: int
    em: float | None
    pitch: float | None          # 相邻正文列中心距中位数（列距）
    rules_v: list[tuple[int, int]]   # 长竖线 [x0, x1) 段
    rules_h: list[tuple[int, int]]   # 长横线 [y0, y1) 段
    runs: list[LineRun]
    block: tuple[int, int, int, int] | None   # 正文块 (x0, y0, x1, y1)，左上原点，半开

    @property
    def body(self) -> list[LineRun]:
        """真正有字的正文列，右→左。"""
        return [r for r in self.runs if r.kind == "body"]

    @property
    def columns(self) -> list[LineRun]:
        """全部列位（body + empty），右→左；`borders` 按这个出。"""
        return [r for r in self.runs if r.kind in ("body", "empty")]


def _runs(mask: np.ndarray, minlen: int = 1) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    s: int | None = None
    for i, v in enumerate(mask):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s >= minlen:
                out.append((s, i))
            s = None
    if s is not None and len(mask) - s >= minlen:
        out.append((s, len(mask)))
    return out


def _longest_run_len(row: np.ndarray) -> int:
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    s = np.flatnonzero(d == 1)
    e = np.flatnonzero(d == -1)
    return int((e - s).max()) if s.size else 0


def long_rules(ink: np.ndarray, min_frac: float = 0.5, h_min_run_frac: float = 0.1,
               h_prefilter_frac: float = 0.01
               ) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """长竖线（列墨占比 ≥ min_frac 的列段）与长横线。

    横线不能只看行墨占比：印得淡/断的栏线整行只有 0.02～0.18（北行日錄扫描页 4 那条），
    跟文字行（0.2～0.45）分不开；分得开的是**最长连续墨段**——线的连续段 ≥ 0.1 页宽
    （断线实测 0.02～0.18 页宽），文字行再密也是一个个字身（≤ 0.03 页宽）。"""
    W = ink.shape[1]
    v = _runs(ink.mean(axis=0) >= min_frac, 1)
    rowfrac = ink.mean(axis=1)
    is_line = np.zeros(ink.shape[0], dtype=bool)
    for y in np.flatnonzero(rowfrac >= h_prefilter_frac):
        if _longest_run_len(ink[y]) >= h_min_run_frac * W:
            is_line[y] = True
    h = _runs(is_line, 1)
    return v, h


def detect_lines(gray: np.ndarray, *, ink_threshold: int = 128, col_ink_min: float = 0.008,
                 min_width_frac: float = 0.15, body_lo: float = 0.75, body_hi: float = 1.35,
                 margin_gap_frac: float = 1.5, jiazhu_gap_frac: float = 0.3,
                 small_col_frac: float = 0.4, rule_pad: int = 4) -> LineLayout:
    H, W = gray.shape[:2]
    ink = gray < ink_threshold
    rules_v, rules_h = long_rules(ink)
    work = ink.copy()
    for a, b in rules_v:
        work[:, max(0, a - rule_pad):min(W, b + rule_pad)] = False
    for a, b in rules_h:
        work[max(0, a - rule_pad):min(H, b + rule_pad), :] = False

    colfrac = work.mean(axis=0)
    # 迟滞：段的**范围**按低门槛（col_ink_min/4）取，段**成立**要求峰值 ≥ col_ink_min。
    # 单一绝对门槛对短列不稳：`colfrac` 是按整幅高平均的，图高一变（分页余量从 30 到 130，
    # 多出 200 行白）短列两侧的边缘笔画就掉到门槛下，列宽缩水——北行日錄 p69「二月」列从
    # 100px 缩成 72px、被判成小字列，整页列数少一，校對本标签整页错位（2026-09-15）。
    low = col_ink_min / 4.0
    segs = [(a, b) for a, b in _runs(colfrac > low, 3) if float(colfrac[a:b].max()) >= col_ink_min]
    if not segs:
        return LineLayout(W, H, None, None, rules_v, rules_h, [], None)
    widths = np.array([b - a for a, b in segs], dtype=float)
    wmax = float(widths.max())
    em = float(np.median(widths[widths >= 0.5 * wmax]))
    runs: list[LineRun] = []
    for a, b in segs:
        w = b - a
        if w < min_width_frac * em:
            continue
        rows = np.flatnonzero(work[:, a:b].any(axis=1))
        runs.append(LineRun(x0=a, x1=b, y0=int(rows[0]), y1=int(rows[-1]), width=w,
                            row_ink=float(rows.size / (rows[-1] - rows[0] + 1))))
    # 斜了的栏线：一条 20px 宽、2200px 高的线只要歪 1° 就横跨 40px，没有哪一列的墨占比到得了
    # long_rules 的 0.5，于是它成了一个「段」——窄、满墨（row_ink ≈ 1）、几乎通页高。这样的段
    # 是竖线不是列，补进 rules_v 并从段里拿掉（北行日錄 p7/p8 书口栏线，2026-09-15：它被当成
    # 小字列后，与书眉小字的中心距 59px 成了列距的最小族，整页插满空列位）。
    keep = []
    for r in runs:
        if r.width < 0.35 * em and r.row_ink >= 0.95 and (r.y1 - r.y0) >= 0.5 * H:
            rules_v = list(rules_v) + [(r.x0, r.x1)]
        else:
            keep.append(r)
    runs = keep
    if not runs:
        return LineLayout(W, H, em, None, rules_v, rules_h, [], None)
    runs.sort(key=lambda r: -r.x0)          # 右→左

    # 粗分类：按宽度
    for r in runs:
        if body_lo * em <= r.width <= body_hi * em:
            r.kind = "body"
        elif r.width < body_lo * em:
            r.kind = "footnote"          # 先当脚注，下面再按位置改成 margin / jiazhu 子列 / small_col
        else:
            r.kind = "wide"
            r.flags.append(f"宽 {r.width}px = {r.width / em:.2f} em，疑似并列/粘连")

    def _pitch_of(body_runs):
        if len(body_runs) < 2:
            return None
        d = np.sort(-np.diff([r.cx for r in body_runs]))   # 右→左，取正
        # 空列位让部分差成倍数，取最小那一族——但族得站得住：至少 2 个、且不少于差数的 1/4。
        # 一对挨得近的杂段（书口栏线渣 + 书眉小字）能造出一个孤零零的 59px「最小差」，
        # 全页列距就跟着它走（p7，2026-09-15）。
        need = max(2, int(np.ceil(0.25 * d.size)))
        for base in d:
            near = d[(d >= base) & (d <= base * 1.5)]
            if near.size >= need:
                return float(np.median(near))
        return float(np.median(d))

    # 列位网格：相位取「与最多正文列同相」的那一列。书口小字（卷次/页码）不在网格上，
    # 脚注列、小注整列在网格上——这是分「块外杂物」与「块内窄列」最硬的判据。
    body = [r for r in runs if r.kind == "body"]
    pitch0 = _pitch_of(body)

    def grid_dev(r) -> float:
        if not pitch0 or len(body) < 3:
            return 0.0
        best = 0
        dev = 0.0
        for anchor in body:
            ds = [abs(((s.cx - anchor.cx) + pitch0 / 2) % pitch0 - pitch0 / 2) for s in body]
            n_on = sum(1 for d in ds if d <= 0.15 * pitch0)
            if n_on > best:
                best = n_on
                dev = abs(((r.cx - anchor.cx) + pitch0 / 2) % pitch0 - pitch0 / 2) / pitch0
        return dev

    # 书口小字（margin）——**先于配对**判，否则卷次小字会跟旁边的栏线渣配成「双行小注列」
    # （2026-09-15 北行日錄 p7/p8）。判据：在长竖线外侧；或整段在正文块之外且（离块超过
    # margin_gap_frac × 列距，或不在列位网格上）——页码「一八三四」宽 80px 够得上正文宽度、
    # 离块只 0.6 列距，但不在网格上（p10）。
    regular = [r for r in body if grid_dev(r) <= 0.25]
    if len(regular) < 3:
        regular = body                       # 卷题页列位本就不等距，网格判据在这种页上不作数
    ref_pitch = pitch0 or em * 1.8
    if regular:
        bx0, bx1 = min(r.x0 for r in regular), max(r.x1 for r in regular)
        bh = max(r.y1 for r in body) - min(r.y0 for r in body)
        for r in runs:
            outside_rule = any((r.x1 <= a and a <= bx0) or (r.x0 >= b and b >= bx1)
                               for a, b in rules_v)
            beyond = r.x1 <= bx0 or r.x0 >= bx1
            gap = min(abs(r.x0 - bx1), abs(bx0 - r.x1)) if beyond else 0
            # 卷次/页码/书眉都短（≤ 1/3 块高）；卷题列（「攻媿先生文集卷第一百十九」12 个大字）
            # 是高的——它离正文块 2.5 列距、也不在网格上，只有「高」能把它从书口小字里救出来。
            short = (r.y1 - r.y0) < 0.35 * bh
            off_grid = grid_dev(r) > 0.25
            if outside_rule or (beyond and short and (gap > margin_gap_frac * ref_pitch or off_grid)):
                r.kind = "margin"
    else:
        for r in runs:
            if r.kind == "footnote":
                r.kind = "margin"

    # 双行小注**整列**：两条相邻窄段（各约半个 em 宽、缝 ≤ 0.25 em）拼起来正好一个字身宽
    # → 一个列位（北行日錄 p52 实测 48+45px、缝 13px）。Step3 还切不了它（两个子列在
    # y 投影上交错），先把列位与序号占对，标 jiazhu_pair 留给 M3。只配块内的窄段。
    paired: list[LineRun] = []
    i = 0
    while i < len(runs):
        r = runs[i]
        if r.kind == "footnote" and i + 1 < len(runs) and runs[i + 1].kind == "footnote":
            s = runs[i + 1]                       # s 在左
            gap, tot = r.x0 - s.x1, r.x1 - s.x0
            textlike = all(x.width >= 0.35 * em and x.row_ink <= 0.92 for x in (r, s))
            if textlike and 0 <= gap <= 0.25 * em and body_lo * em <= tot <= body_hi * em:
                paired.append(LineRun(x0=s.x0, x1=r.x1, y0=min(r.y0, s.y0), y1=max(r.y1, s.y1),
                                      width=tot, kind="body", flags=["jiazhu_pair"]))
                i += 2
                continue
        paired.append(r)
        i += 1
    runs = paired

    # 双行小注**子列**：贴着正文列、y 范围在它里面 → 并回去（卷题下的小注：右子列与
    # 大字连成一段，左子列自成一条窄段）
    merged: list[LineRun] = []
    for r in runs:
        if r.kind == "footnote":
            host = next((b for b in runs if b.kind == "body" and
                         (0 <= b.x0 - r.x1 <= jiazhu_gap_frac * em or 0 <= r.x0 - b.x1 <= jiazhu_gap_frac * em)
                         and b.y0 - 2 <= r.y0 and r.y1 <= b.y1 + 2), None)
            if host is not None:
                host.x0, host.x1 = min(host.x0, r.x0), max(host.x1, r.x1)
                host.width = host.x1 - host.x0
                host.flags.append("jiazhu_sub")
                continue
        merged.append(r)
    runs = merged

    body = [r for r in runs if r.kind == "body"]
    if body:
        # 小字整列：块内、够长（≥ small_col_frac × 正文块高）的窄段是一列小字——脚注列、
        # 单行小注整列。它占一个列位、在校對本里也是一行，所以当 body 编号，标 small_col。
        bh = max(r.y1 for r in body) - min(r.y0 for r in body)
        for r in runs:
            if r.kind == "footnote" and (r.y1 - r.y0) >= small_col_frac * bh:
                r.kind = "body"
                r.flags.append("small_col")
    body = [r for r in runs if r.kind == "body"]
    pitch = _pitch_of(body)

    # 空列位：相邻正文列中心距 ≈ k × 列距（k ≥ 2）时补 k−1 个
    if pitch and len(body) >= 2:
        by0 = min(r.y0 for r in body)
        by1 = max(r.y1 for r in body)
        extra: list[LineRun] = []
        for a, b in zip(body, body[1:]):            # a 在右
            k = int(round((a.cx - b.cx) / pitch))
            for t in range(1, max(k, 1)):
                cx = a.cx - t * pitch
                extra.append(LineRun(x0=int(round(cx - em / 2)), x1=int(round(cx + em / 2)),
                                     y0=by0, y1=by1, width=int(round(em)), kind="empty"))
        runs.extend(extra)
        runs.sort(key=lambda r: -r.x0)

    n = 0
    for r in runs:
        if r.kind in ("body", "empty"):
            n += 1
            r.col = n
    block = None
    if body:
        block = (min(r.x0 for r in body), min(r.y0 for r in body),
                 max(r.x1 for r in body), max(r.y1 for r in body) + 1)
    return LineLayout(W, H, em, pitch, rules_v, rules_h, runs, block)


def layout_to_borders(lay: LineLayout, *, pad_frac: float = 0.6) -> BorderDetectionResult | None:
    """列位 → 刻本链同款 `BorderDetectionResult`（右上原点）。没有正文列返回 None。

    虚拟界行取相邻列位的**中线**；最外两条在块边外半个列间空白处，与内侧界行到列边的
    距离一致，这样每列窗口两侧留白相同，闸2 的列宽一致性判据（L1c）才不会把首末列当异常。
    上下框 = 正文块上下沿各外扩 `pad_frac × em`（要 > Step4 extractor 找框线行的窗口
    FRAME_HINT_TOL=40px，否则首末字的横笔会被当成框线）。
    """
    cols = lay.columns
    if not lay.body:
        return None
    W, H = lay.width, lay.height
    em = lay.em or float(np.median([r.width for r in lay.body]))
    gap = (lay.pitch - em) if lay.pitch else em * 0.8
    half = max(2.0, gap / 2.0)
    xs_tl: list[float] = [cols[0].x1 + half]          # 最右一条（第 1 列右界）
    for a, b in zip(cols, cols[1:]):                  # a 在右、b 在左
        xs_tl.append((a.x0 + b.x1) / 2.0)
    xs_tl.append(cols[-1].x0 - half)                  # 最左一条
    verticals = [VLine(x_at_top=float((W - 1) - x), slope=0.0) for x in xs_tl]
    y_top = max(0.0, min(r.y0 for r in lay.body) - pad_frac * em)
    y_bot = min(float(H - 1), max(r.y1 for r in lay.body) + pad_frac * em)
    return BorderDetectionResult(
        width=W, height=H,
        top=HLine(y_at_right=float(y_top), slope=0.0, kind="top"),
        bottom=HLine(y_at_right=float(y_bot), slope=0.0, kind="bottom"),
        verticals=verticals, head_raise=[], vline_segments=1,
        verticals_straight=list(verticals))
