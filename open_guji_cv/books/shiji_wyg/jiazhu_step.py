"""雙行小注逐步切（史記文淵閣本，`row_segment.jiazhu_step_split`，2026-11-04，SJ；A22 评审过）。

为什么
------
写本雙行小注的小字行距比正文格网小，两行字数也常不等（长行可以是右行 a，也可以是左行 b）。
共用格线切的时候，长的那一行被压进短行的格数里，从并字的地方起一路错下去（第 8 轮正文约 41 格「一个
半格里并进两个小字」：08:5:4 b 行 14 字、a 行 13 字只给了 13 格，b 首格并进「子故」）。

做法（规则见 ai-team domain/CV/质检/史記-r8-交A22/A22-夹注逐步v1字id规则.md，及 A22 11-04 的五点补充）
------------------------------------------------------------------------------------------------
在挑定的格网上做后处理，只动整理本（殆知阁）认得出分法的夹注段：
1. 每段的两行字数 m_a（右行）、m_b（左行）取整理本 `<右|左>` 的分法（daizhige note 的 r/l），墨只用来核对与定切线。
2. 段占格号 L＝max(m_a, m_b)：s0…s0+L−1（格位表本来就按这个记，`layout_slots_grow` 开着时格号已是逻辑位）。
3. 段在图上的真实下沿：段顶往下，缝中带（缝心 ±`MID_BAND` 列宽）连续 `MAIN_RUN`×格高有墨的地方是段下正文字的起头。
4. 两行各在自己墨的范围里按自己的字数切（`seg.seam.fit_row_cuts`）；短行末格保留 #947 的「段下正文字探上来就跳过」守卫。
5. 段下到下一段（或列尾）的正文格按格位表的格数在墨投影上重切。
6. 任一段核不上（墨与字数对不上、半格墨不够、切线横穿字、段在图上比 L 格还长〔Δ<0〕），整列退回原切法并打旗。
7. 两行分法不是「a＝⌈N/2⌉、b＝⌊N/2⌋」的段打 `jiazhu_uneven` 旗送审（规则九）。

有列级人裁的列（pins、resolved_cuts、强制單行／夹注／正文、human_col）不走这里（规则七），由调用方判。
跨列的段（整理本这一列只有段的一部分）照本列那部分的字数算，Δ 只影响本列。
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

#: 缝中带半宽（列宽的比例）：正文字横画穿过这里，雙行小注两行之间这里是白的
MID_BAND = 0.06
#: 缝中带连续有墨这么多格高，算段下正文字起头
MAIN_RUN = 0.3
#: 缝中带一行有墨的门槛（带宽的比例）
MID_INK = 0.25
#: 段在图上的高度不许超过 L 格的这么多倍（Δ<0：图上的段比整理本的字数长，先退回旧切法）
MAX_SEG_RATIO = 1.15
#: 半格、正文格至少这么多墨（px），不然这一切法不成立
MIN_INK = 30
#: 每格墨至少是本行格墨中位数的这么多（防切出空格、把两字并一格）
MIN_INK_REL = 0.1
#: 每行末尾墨的判据与守卫（同 row_boundaries._free_split）
END_INK = 0.02
END_PAD = 3
END_MAX_DEPTH = 0.5
#: 切线处（±1 行最白的一行）墨占比到这么多算横穿字
CUT_INK = 0.15
#: v1.1 段首从墨上找（第 11 轮，03:144:2「竹」被劈进夹注第一格）：格网段顶上下找的范围、缝要连续空多高、挪多少才认
HEAD_UP, HEAD_DOWN, HEAD_MERGE, HEAD_MIN_H, HEAD_MIN_H2, HEAD_AGREE, HEAD_MIN_MOVE = 0.6, 1.3, 0.04, 0.3, 0.12, 0.2, 0.2

_PINS: dict[str, dict] = {}
_RECS: dict[str, dict] = {}


def _pins(path: str) -> dict:
    if path not in _PINS:
        out = {}
        for ln in Path(path).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                out[(str(r["book"]), int(r["page"]))] = str(r["head"]).strip()
        _PINS[path] = out
    return _PINS[path]


def _recs(dz_dir: str) -> dict:
    if dz_dir not in _RECS:
        recs = {}
        for f in sorted(Path(dz_dir).glob("[0-9][0-9][0-9][0-9].jsonl")):
            for ln in f.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    r = json.loads(ln)
                    recs[r["id"]] = r
        _RECS[dz_dir] = recs
    return _RECS[dz_dir]


def page_note_runs(dz_dir, pins_file, book: str, page: int) -> dict[int, list[tuple[int, int, int]]] | None:
    """这一页各列的雙行小注段：{列号: [(段首格号 s0, m_a, m_b), …]}（按 s0 升序）。

    只收两行都是一整段（r、l 各一截、偏移 0）的；有断开、空格的段不收（退回旧切法）。钉位或记录缺失返回 None。"""
    head = _pins(str(pins_file)).get((str(book), int(page)))
    if not head:
        return None
    rid, _leaf, side = head.split()
    rec = _recs(str(dz_dir)).get(rid)
    if rec is None or not isinstance(rec.get("cols"), list):
        return None
    ncol = int((rec.get("geom") or {}).get("ncol") or 8)
    side_i = int(side[1:])
    out: dict[int, list[tuple[int, int, int]]] = {}
    for c in rec["cols"]:
        if c["no"] // ncol != side_i:
            continue
        segs = []
        for r in c.get("runs", []):
            if r.get("t") != "note":
                continue
            rr, ll = r.get("r") or [], r.get("l") or []
            if len(rr) != 1 or len(ll) != 1 or rr[0][0] != 0 or ll[0][0] != 0:
                continue
            m_a, m_b = len(rr[0][1]), len(ll[0][1])
            start = int(r["start"])
            if start < 0 or m_a < 1 or m_b < 1:
                continue
            segs.append((start + 1, m_a, m_b))
        if segs:
            out[c["no"] % ncol + 1] = sorted(segs)
    return out


def _row_frac(ink: np.ndarray, xs: int, xe: int) -> np.ndarray:
    return ink[:, xs:xe].sum(axis=1) / float(max(1, xe - xs))


def _seg_end(ink: np.ndarray, top: int, bot: int, cx: int, period: float) -> int:
    """段顶往下，缝中带连续 MAIN_RUN 格高有墨处（段下正文字起头）；没有就 bot。"""
    w = ink.shape[1]
    half = max(2, int(round(MID_BAND * w)))
    band = ink[:, max(0, cx - half):min(w, cx + half + 1)]
    on = band.mean(axis=1) >= MID_INK
    run = max(3, int(round(MAIN_RUN * period)))
    y = top + int(round(0.5 * period))
    while y + run <= bot:
        if on[y:y + run].all():
            # 往回找到这段墨的起头
            while y > top and on[y - 1]:
                y -= 1
            return y
        y += 1
    return bot


def _char_runs(full: np.ndarray, y_top: int, merge: float, min_h: float) -> list[list[int]]:
    """整列横向投影从 y_top 往下的一段段墨：间隔短于 merge 的并起来，矮于 min_h 的扔掉（单位：行）。"""
    runs: list[list[int]] = []
    y, n = y_top, len(full)
    while y < n:
        if full[y]:
            e = y
            while e < n and full[e]:
                e += 1
            if runs and y - runs[-1][1] < merge:
                runs[-1][1] = e
            else:
                runs.append([y, e])
            y = e
        else:
            y += 1
    return [r for r in runs if r[1] - r[0] >= min_h]


def _seg_head(ink: np.ndarray, y_top: int, n_pre: int, top: int, period: float) -> int | None:
    """段首从墨上找（v1.1）：从列首格顶往下数正文大字（整列横向投影的一段段墨），第 n_pre 个字的下沿与下一段墨的
    起头取中点作段首。中缝本来空着的大字（竹、林、川）不会被当成两行小注的起头。
    「二」「三」这类笔画间有白缝的字会数乱：用两种「多矮算碎笔」（HEAD_MIN_H 与 HEAD_MIN_H2）各数一遍，段首对不上
    （差 ≥ HEAD_AGREE 格高）就不认；数不出、或离格网段顶超出 HEAD_UP／HEAD_DOWN 格高也给 None。"""
    full = ink.mean(axis=1) >= END_INK
    heads = []
    for min_h in (HEAD_MIN_H, HEAD_MIN_H2):
        runs = _char_runs(full, y_top, HEAD_MERGE * period, min_h * period)
        if len(runs) <= n_pre:
            return None
        heads.append((runs[n_pre - 1][1] + runs[n_pre][0]) // 2)
    if max(heads) - min(heads) >= HEAD_AGREE * period:
        return None
    head = heads[0]
    if not top - HEAD_UP * period <= head <= top + HEAD_DOWN * period:
        return None
    return head


def _line_end(rows: np.ndarray, top: int, end: int, limit: float) -> int | None:
    """一行墨的末行（同 _free_split：起头比 limit 还深的墨段算段下正文字探上来的笔画，跳过）。"""
    ys = top + np.flatnonzero(rows[top:end] >= END_INK)
    k = len(ys) - 1
    while k >= 0:
        j = k
        while j > 0 and ys[j] - ys[j - 1] <= END_PAD + 1:
            j -= 1
        if ys[j] < limit:
            return min(end, int(ys[k]) + 1 + END_PAD)
        k = j - 1
    return None


def _cuts_ok(ink: np.ndarray, rows: np.ndarray, cuts: list[float], xs: int, xe: int) -> bool:
    """每格都有字（墨 ≥ MIN_INK，且 ≥ 本行格墨中位的 MIN_INK_REL），切线不横穿字。"""
    am = [int(ink[int(round(y0)):int(round(y1)), xs:xe].sum()) for y0, y1 in zip(cuts[:-1], cuts[1:])]
    med = float(np.median(am)) if am else 0.0
    if any(a < MIN_INK or a < MIN_INK_REL * med for a in am):
        return False
    return not any(float(rows[max(0, int(round(c)) - 1):int(round(c)) + 2].min()) >= CUT_INK for c in cuts[1:-1])


def _ink_ratio(patch: np.ndarray, ink_threshold: int) -> float:
    return 0.0 if patch.size == 0 else float((patch < ink_threshold).sum()) / float(patch.size)


def restep(cells: list, col_gray: np.ndarray, content_x: tuple[float, float], period: float,
           specs: list[tuple[int, int, int]], ink_threshold: int = 128, reading_order=None):
    """见 `_restep`。段首按墨挪过（v1.1）却切不出时，退回按格网段顶再切一遍（即 v1 的切法），不因段首挪错丢掉整列。"""
    out, flags = _restep(cells, col_gray, content_x, period, specs, ink_threshold, reading_order, use_head=True)
    if out is None and flags:
        return _restep(cells, col_gray, content_x, period, specs, ink_threshold, reading_order, use_head=False)
    return out, flags


def _restep(cells: list, col_gray: np.ndarray, content_x: tuple[float, float], period: float,
            specs: list[tuple[int, int, int]], ink_threshold: int = 128, reading_order=None, use_head: bool = True):
    """挑定格网的一列格子按整理本分法重切夹注段（见模块头）。

    返回 (新格子列表, 旗) ；核不上返回 (None, 旗)，调用方留原切法。`cells` 是壳的 `Cell`（按 `type(cells[0])` 造新格，
    套书之间不互相 import）；`reading_order` 是壳给的读序函数。"""
    from ...seg.seam import fit_row_cuts
    if not cells:
        return None, []
    Cell = type(cells[0])
    if col_gray.ndim == 3:
        col_gray = col_gray[:, :, 0]
    x_lo, x_hi = int(round(content_x[0])), int(round(content_x[1]))
    ink = col_gray[:, x_lo:x_hi] < ink_threshold
    w = x_hi - x_lo
    by_slot: dict[int, list] = {}
    for c in cells:
        by_slot.setdefault(c.slot, []).append(c)
    slots = sorted(by_slot)
    if not slots or not specs:
        return None, []
    # 原切法每段两行的格数已和整理本分法一致的列不动（只改切错的列，免得误伤切对的）
    def _n(sub, s0, L):
        return sum(1 for s in range(s0, s0 + L) for c in by_slot.get(s, ()) if c.kind == "jiazhu_" + sub)
    if all(_n("a", s0, max(ma, mb)) == ma and _n("b", s0, max(ma, mb)) == mb for s0, ma, mb in specs):
        return None, []
    last_slot = slots[-1]
    col_bot = int(round(max(c.y1 for c in cells)))
    flags: list[str] = []
    out: list = [c for c in cells if c.slot < specs[0][0]]
    plan = []          # (s0, L, top, end, cx, m_a, m_b)
    # 先定每段的顶、缝、图上下沿
    prev_end = None
    head_moved = False
    for s0, m_a, m_b in specs:
        L = max(m_a, m_b)
        head = by_slot.get(s0)
        if not head:
            return None, [f"jiazhu_step：段 {s0} 在格网里没有格，退回"]
        top = int(round(min(c.y0 for c in head)))
        if prev_end is not None:
            top = max(top, prev_end)
        gcs = [c.gap_center for s in range(s0, s0 + L) for c in by_slot.get(s, ()) if c.gap_center is not None]
        if not gcs:
            return None, [f"jiazhu_step：段 {s0} 认不出缝，退回"]
        cx = int(round(float(np.median(gcs)))) - x_lo
        if not 4 <= cx <= w - 4:
            return None, [f"jiazhu_step：段 {s0} 缝贴边，退回"]
        if prev_end is None and use_head:
            pre = sorted((c for c in out if c.kind != "blank"), key=lambda c: c.y0)
            ht = (_seg_head(ink, int(round(pre[0].y0)), len({c.slot for c in pre}), top, period)
                  if pre and len(pre) == len(out) else None)
            if ht is not None and abs(ht - top) >= HEAD_MIN_MOVE * period and pre and len(pre) == len(out) \
                    and ht - pre[0].y0 >= 0.5 * period * len({c.slot for c in pre}):
                top = ht
                head_moved = True
        end = _seg_end(ink, top, col_bot, cx, period)
        if end - top > MAX_SEG_RATIO * L * period:
            return None, [f"jiazhu_step：段 {s0} 图上比 {L} 格长（Δ<0），退回"]
        plan.append((s0, L, top, end, cx, m_a, m_b))
        prev_end = end
    new: list = []
    if head_moved:
        # 段首挪了：段前的正文格（第一段之前、列首起）按原格数在 [列首格顶, 段首) 里重切
        pre_slots = sorted({c.slot for c in out})
        y_top = min(c.y0 for c in out)
        full = ink.sum(axis=1) / float(max(1, w))
        cuts = fit_row_cuts(full, int(round(y_top)), plan[0][2], len(pre_slots))
        if cuts is None:
            return None, [f"jiazhu_step：段 {plan[0][0]} 段首挪后，段前正文 {len(pre_slots)} 格切不出，退回"]
        old_by = {c.slot: c for c in out}
        out = []
        for s, y0, y1 in zip(pre_slots, cuts[:-1], cuts[1:]):
            r = _ink_ratio(col_gray[int(y0):int(y1), x_lo:x_hi], ink_threshold)
            old = old_by[s]
            kind = "blank" if r < 0.01 else ("char" if old.kind in ("char", "blank", "punct") else old.kind)
            out.append(Cell(slot=s, y0=float(y0), y1=float(y1), x0=float(x_lo), x1=float(x_hi),
                            kind=kind, ink_ratio=round(r, 4)))
        flags.append(f"jiazhu_head：段 {plan[0][0]} 段首按墨挪到 y={plan[0][2]}")
    for i, (s0, L, top, end, cx, m_a, m_b) in enumerate(plan):
        rows = {"a": _row_frac(ink, cx, w), "b": _row_frac(ink, 0, cx)}
        spans = {"a": (cx, w), "b": (0, cx)}
        cuts_by: dict[str, list[float]] = {}
        for sub, m in (("a", m_a), ("b", m_b)):
            # 每行墨的末行：段下正文字起头 end 往上 END_MAX_DEPTH 格高以内起头的墨段是正文字探上来的笔画，跳过
            e = _line_end(rows[sub], top, end, end - END_MAX_DEPTH * period)
            if e is None:
                return None, [f"jiazhu_step：段 {s0} {sub} 行找不到墨的末行，退回"]
            cuts = fit_row_cuts(rows[sub], top, e, m)
            if cuts is None or not _cuts_ok(ink, rows[sub], cuts, *spans[sub]):
                return None, [f"jiazhu_step：段 {s0} {sub} 行切不出 {m} 字，退回"]
            cuts_by[sub] = cuts
        for sub, cuts in cuts_by.items():
            xs, xe = spans[sub]
            for k in range(len(cuts) - 1):
                y0, y1 = float(cuts[k]), float(cuts[k + 1])
                new.append(Cell(slot=s0 + k, y0=y0, y1=y1, x0=float(x_lo + xs), x1=float(x_lo + xe),
                                kind="jiazhu_" + sub, gap_center=float(x_lo + cx),
                                ink_ratio=round(_ink_ratio(col_gray[int(y0):int(y1), x_lo + xs:x_lo + xe],
                                                           ink_threshold), 4)))
        n = (m_a + m_b)
        if not (m_a == (n + 1) // 2 and m_b == n // 2):
            flags.append(f"jiazhu_uneven:{s0}-{s0 + L - 1}：右 {m_a} 左 {m_b}（整理本分法），送审")
        # 段下到下一段（或列尾）的正文格
        nxt = plan[i + 1] if i + 1 < len(plan) else None
        lo_s, hi_s = s0 + L, (nxt[0] - 1) if nxt else last_slot
        main_slots = [s for s in range(lo_s, hi_s + 1) if s != 0]
        if main_slots:
            bot = nxt[2] if nxt else col_bot
            full = ink.sum(axis=1) / float(max(1, w))
            cuts = fit_row_cuts(full, end, bot, len(main_slots))
            if cuts is None:
                return None, [f"jiazhu_step：段 {s0} 下的正文 {len(main_slots)} 格切不出，退回"]
            for s, y0, y1 in zip(main_slots, cuts[:-1], cuts[1:]):
                patch = col_gray[int(y0):int(y1), x_lo:x_hi]
                r = _ink_ratio(patch, ink_threshold)
                old = by_slot.get(s, [None])[0]
                kind = "blank" if r < 0.01 else ("char" if old is None or old.kind in ("char", "blank", "punct")
                                                  or old.kind.startswith("jiazhu") else old.kind)
                new.append(Cell(slot=s, y0=float(y0), y1=float(y1), x0=float(x_lo), x1=float(x_hi),
                                kind=kind, ink_ratio=round(r, 4)))
    out += new
    for i, c in enumerate(reading_order(out) if reading_order else sorted(out, key=lambda c: c.slot), start=1):
        c.order = i
    return sorted(out, key=lambda c: (c.slot, c.kind)), flags


def apply(res, col_gray, content_x, period, specs, ink_threshold: int = 128, reading_order=None):
    """`RowBoundaryResult` 上做逐步切：成了换 cells（boundaries 不动），去掉动过的格的折线候选。返回 (res, 旗)。"""
    cells, flags = restep(res.cells, col_gray, content_x, period, specs, ink_threshold, reading_order)
    if cells is None:
        return res, flags
    s_min = min(s for s, _a, _b in specs)
    cands = [cp for cp in res.cut_candidates if cp.slot_below < s_min]
    return replace(res, cells=cells, cut_candidates=cands), flags + ["jiazhu_step：按整理本分法逐步切"]
