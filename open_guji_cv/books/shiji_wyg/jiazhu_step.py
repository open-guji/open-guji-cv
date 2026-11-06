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
   v1.2（11-05，SJ）：图上能证明分法的段不送审，旗改记 `jiazhu_uneven_img`（见 `_split_proven`）：整理本分法两行
   切出来的格高都匀（格高 ÷ 中位在 [1−UNEVEN_Q, 1+UNEVEN_Q] 内），且总字数不变、往一边挪 1～2 字的分法要么切不通、
   要么格高明显更不匀（差 ≥ UNEVEN_MARGIN）。第 11 轮结构批 8 列 62 格看图：6 列分法对、2 列（03:90:3、08:11:8）
   该送审，这条判据正好分开。
8. 段下沿（v1.2）：缝中带判据找出的下沿比 L 格长出 SEG_GAP_TRY 倍以上时，再找一次「整行白 ≥ GAP_WHITE 格高、
   紧接着缝中带有墨」的地方当下沿（`_seg_end_gap`）：段下正文字中间是空的（皆、白、比）时缝中带断开，原判据会一直找到下面的字。
9. v1.2：原切法格数已对上的列，原格有空格或两字一格（`_orig_placed_ok`）也重切；第二段起的段首也按段间正文字数从墨上找。
   v1.3（11-05，第 13 轮验收）：这类格数本来对的列不挪段首、不按段下沿判，新切法毛病格要少、格高不能更不匀才换。
   v1.4（11-06，第 14 轮验收）：毛病格一样多、格高明显更匀（偏离小 BETTER_Q 以上）也换，补回 v1.3 丢掉的两字并一格的列。

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
#: 分法证明（v1.2）：整理本分法格高的最大偏离（格高 ÷ 本行中位 − 1 的绝对值）不过这个
UNEVEN_Q = 0.25
#: 挪 1～2 字的分法格高偏离至少比整理本分法大这么多，才算图上只有整理本这一种分法
UNEVEN_MARGIN = 0.1
#: 段下沿再找（v1.2）：原下沿比 L 格高长出这么多倍才再找；新下沿至少在 L 格高的这么多倍以下
SEG_GAP_TRY = 1.05
SEG_GAP_MIN = 0.8
#: 格数对上的原切法，一行里最高的格超过本行格高中位这么多倍（多半两字并一格）也重切（v1.2）
ORIG_HMAX = 1.5
#: 末段到列尾：列尾起头深的墨段有这么多格高才算末字（v1.2）
TAIL_KEEP_H = 0.3
#: 这类列新切法格高偏离最多可以比原来大这么多（v1.3）
BETTER_Q_WORSE = 0.05
#: 毛病格一样多时，新切法格高偏离要比原来小这么多才换（v1.4）
BETTER_Q = 0.15
#: 整行白至少这么多格高
GAP_WHITE = 0.12
#: 白行之后这么多格高里缝中带有墨的行占比到 GAP_BAND_FRAC 算正文字起头
GAP_BAND_RUN = 0.25
GAP_BAND_FRAC = 0.6
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


def _seg_end_gap(ink: np.ndarray, lo: int, hi: int, cx: int, period: float) -> int | None:
    """[lo, hi) 里第一处「整行白 ≥ GAP_WHITE 格高、紧接着 GAP_BAND_RUN 格高里缝中带有墨的行占 GAP_BAND_FRAC」→ 白段下沿。"""
    w = ink.shape[1]
    half = max(2, int(round(MID_BAND * w)))
    on = ink[:, max(0, cx - half):min(w, cx + half + 1)].mean(axis=1) >= MID_INK
    white = ink.sum(axis=1) <= max(1, int(0.005 * w))
    g = max(3, int(round(GAP_WHITE * period)))
    r = max(3, int(round(GAP_BAND_RUN * period)))
    run = 0
    for y in range(max(0, lo), min(hi, ink.shape[0] - r)):
        run = run + 1 if white[y] else 0
        if run >= g and not white[y + 1] and on[y + 1:y + 1 + r].mean() >= GAP_BAND_FRAC:
            return y + 1
    return None


def _seg_end_white(ink: np.ndarray, top: int, L: int, period: float) -> int | None:
    """末一招（v1.2）：段顶下 [SEG_GAP_MIN, MAX_SEG_RATIO]×L 格高里整行白 ≥ GAP_WHITE 格高的白段，取下沿离 L 格高最近的。
    段下正文字缝中带也没墨（浮：氵＋孚）时用（02:104:2 段 1 只有两行小字）。"""
    w = ink.shape[1]
    white = ink.sum(axis=1) <= max(1, int(0.005 * w))
    g = max(3, int(round(GAP_WHITE * period)))
    lo, hi = int(round(top + SEG_GAP_MIN * L * period)), min(ink.shape[0] - 1, int(round(top + MAX_SEG_RATIO * L * period)))
    want = top + L * period
    best, run = None, 0
    for y in range(max(top, lo - g), hi + 1):
        run = run + 1 if white[y] else 0
        if run >= g and y + 1 >= lo and not white[min(y + 1, len(white) - 1)]:
            if best is None or abs(y + 1 - want) < abs(best - want):
                best = y + 1
    return best


def _seg_end_fallback(ink: np.ndarray, top: int, end: int, cx: int, L: int, period: float) -> int | None:
    """缝中带判据的下沿太深时再找（v1.2）：先白行＋缝中带（只在 MAX_SEG_RATIO×L 格高以内找），再整行白段。"""
    hi = min(end, int(round(top + MAX_SEG_RATIO * L * period)) + 1)
    e2 = _seg_end_gap(ink, int(round(top + SEG_GAP_MIN * L * period)), hi, cx, period)
    if e2 is None and end - top > MAX_SEG_RATIO * L * period:
        e2 = _seg_end_white(ink, top, L, period)
    return e2


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


def _line_end(rows: np.ndarray, top: int, end: int, limit: float, keep_h: float | None = None) -> int | None:
    """一行墨的末行（同 _free_split：起头比 limit 还深的墨段算段下正文字探上来的笔画，跳过）。
    keep_h（v1.2，末段到列尾）：下面没有正文字，起头深但有 keep_h 高的墨段是本行末字，不跳（框线残渣矮，照跳）。"""
    ys = top + np.flatnonzero(rows[top:end] >= END_INK)
    k = len(ys) - 1
    while k >= 0:
        j = k
        while j > 0 and ys[j] - ys[j - 1] <= END_PAD + 1:
            j -= 1
        if ys[j] < limit or (keep_h is not None and ys[k] - ys[j] >= keep_h):
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


def _raised_is_note(ink: np.ndarray, y0: int, y1: int, cx: int, period: float) -> bool:
    """[y0, y1) 的墨像两行小注的一行（v1.2）：缝两边各有墨（≥ MIN_INK），缝中带没有连续 MAIN_RUN 格高的墨（不是正文大字）。"""
    if y1 - y0 < 0.3 * period:
        return False
    w = ink.shape[1]
    if int(ink[y0:y1, :cx].sum()) < MIN_INK or int(ink[y0:y1, cx:].sum()) < MIN_INK:
        return False
    half = max(2, int(round(MID_BAND * w)))
    on = ink[y0:y1, max(0, cx - half):min(w, cx + half + 1)].mean(axis=1) >= MID_INK
    run = max(3, int(round(MAIN_RUN * period)))
    best = cur = 0
    for v in on:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best < run


def _orig_placed_ok(ink: np.ndarray, by_slot: dict, specs, x_lo: int, w: int, period: float) -> bool:
    """格数已对上的原切法，位置也对吗（v1.2，v1.3 收窄）：每行原格都有字、最高的格不过 ORIG_HMAX 倍中位
    （02:104:8：段首两字并一格、末格空；05:48:8：两字一格），段的第一行也没被抬成列首空格（见 `_raised_is_note`）。
    认不出缝的段不判（当对）。"""
    for s0, m_a, m_b in specs:
        L = max(m_a, m_b)
        cs = [c for s in range(s0, s0 + L) for c in by_slot.get(s, ()) if c.kind.startswith("jiazhu")]
        gcs = [c.gap_center for c in cs if c.gap_center is not None]
        if not cs or not gcs:
            continue
        top = int(round(min(c.y0 for c in cs)))
        cx = int(round(float(np.median(gcs)))) - x_lo
        if not 4 <= cx <= w - 4:
            continue
        # 每行原格：都有字、格高不过分不匀（02:104:8 段首两字并一格、末格空；02:104:7 两字一格）
        for sub in ("a", "b"):
            row = sorted((c for c in cs if c.kind == "jiazhu_" + sub), key=lambda c: c.y0)
            if len(row) < 2:
                continue
            xs, xe = (cx, w) if sub == "a" else (0, cx)
            am = [int(ink[int(round(c.y0)):int(round(c.y1)), xs:xe].sum()) for c in row]
            med_a = float(np.median(am))
            hs = np.asarray([c.y1 - c.y0 for c in row], dtype=float)
            med_h = float(np.median(hs))
            if any(a < MIN_INK or a < MIN_INK_REL * med_a for a in am) or (med_h > 0 and hs.max() > ORIG_HMAX * med_h):
                return False
        raised = [c for s, cl in by_slot.items() if s <= 0 for c in cl]
        if s0 == 1 and raised and _raised_is_note(ink, int(round(min(c.y0 for c in raised))), top, cx, period):
            return False                      # 段的第一行被格网抬成了列首空格
        # v1.3：不再按「原格压过图上段下沿」判（缝中带判据会把横跨缝的小字「舜」「也」当成段下正文字，
        # 第 13 轮 02:37:1、02:56:4、02:56:5 因此把切对的列改坏）
    return True


def _seg_score(ink: np.ndarray, x_lo: int, cells: list, specs) -> tuple[int, float]:
    """各段夹注格的图上毛病（v1.2）：(空格＋切线横穿字的格数, 各行格高最大偏离)。"""
    bad, q = 0, 0.0
    for s0, m_a, m_b in specs:
        L = max(m_a, m_b)
        for sub in ("a", "b"):
            row = sorted((c for c in cells if c.kind == "jiazhu_" + sub and s0 <= c.slot < s0 + L), key=lambda c: c.y0)
            hs = []
            for c in row:
                xs, xe = int(round(c.x0)) - x_lo, int(round(c.x1)) - x_lo
                y0, y1 = int(round(c.y0)), int(round(c.y1))
                hs.append(y1 - y0)
                if int(ink[y0:y1, xs:xe].sum()) < MIN_INK:
                    bad += 1
                    continue
                for y in (y0, y1):
                    if 1 <= y < ink.shape[0] - 1 and float(ink[y - 1:y + 2, xs:xe].mean(axis=1).min()) >= CUT_INK:
                        bad += 1
                        break
            if len(hs) >= 2:
                med = float(np.median(hs))
                if med > 0:
                    q = max(q, float(np.abs(np.asarray(hs) / med - 1.0).max()))
    return bad, q


def _better(ink: np.ndarray, x_lo: int, old: list, new: list, specs) -> bool:
    """新切法比原切法好（v1.4）：毛病格少且格高偏离不比原来大过 BETTER_Q_WORSE；或毛病格一样多、格高偏离小 BETTER_Q 以上。"""
    bo, qo = _seg_score(ink, x_lo, old, specs)
    bn, qn = _seg_score(ink, x_lo, new, specs)
    # v1.3：只在毛病格确实少了、格高也没更不匀时才换（第 13 轮 01:60:8、02:56:5 毛病格少了、格却切错）
    # v1.4：毛病格一样多、格高明显更匀（差 ≥ BETTER_Q）也换（第 14 轮 02:104:7「云密」、02:12:6「上洛」、05:48:8「集解」两字并一格，
    # 新切法毛病格同为 0、格高偏离从 0.4–0.6 降到 0.1 上下，v1.3 因只认「毛病格少了」没换）
    return (bn < bo and qn <= qo + BETTER_Q_WORSE) or (bn == bo and qn + BETTER_Q <= qo)


def _row_q(ink: np.ndarray, rows: np.ndarray, top: int, e: int, m: int, xs: int, xe: int) -> float:
    """一行在 [top, e) 里切 m 字：格高最大偏离（|格高 ÷ 中位 − 1| 的最大值）；切不通返回 inf。"""
    from ...seg.seam import fit_row_cuts
    if m < 1:
        return float("inf")
    cuts = fit_row_cuts(rows, top, e, m)
    if cuts is None or not _cuts_ok(ink, rows, cuts, xs, xe):
        return float("inf")
    hs = np.diff(np.asarray(cuts, dtype=float))
    med = float(np.median(hs))
    return float(np.abs(hs / med - 1.0).max()) if med > 0 else float("inf")


def _split_proven(ink, rows: dict, spans: dict, top: int, ends: dict, m_a: int, m_b: int) -> tuple[float, float]:
    """分法证明（v1.2）→ (整理本分法两行格高偏离的较大者, 挪 ±1、±2 字各分法里偏离最小的)。"""
    def q(ma, mb):
        return max(_row_q(ink, rows["a"], top, ends["a"], ma, *spans["a"]),
                   _row_q(ink, rows["b"], top, ends["b"], mb, *spans["b"]))
    alts = [q(m_a + d, m_b - d) for d in (1, -1, 2, -2) if m_a + d >= 1 and m_b - d >= 1]
    return q(m_a, m_b), (min(alts) if alts else float("inf"))


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
    counts_ok = all(_n("a", s0, max(ma, mb)) == ma and _n("b", s0, max(ma, mb)) == mb for s0, ma, mb in specs)
    if counts_ok and _orig_placed_ok(ink, by_slot, specs, x_lo, w, period):
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
            # v1.2：后面的段的段首也从墨上找（段间正文字数是格位表定的）：格网把段间正文的末字并进下一段时（05:6:1「曰」）
            n_main = len([s for s in range(plan[-1][0] + plan[-1][1], s0) if s != 0])
            ht = (_seg_head(ink, prev_end, n_main, top, period)
                  if (use_head and not counts_ok and n_main >= 1) else None)
            if ht is not None and abs(ht - top) >= HEAD_MIN_MOVE * period \
                    and ht - prev_end >= 0.5 * period * n_main:
                flags.append(f"jiazhu_head：段 {s0} 段首按墨挪到 y={ht}（原 {top}）")
                top = ht
        gcs = [c.gap_center for s in range(s0, s0 + L) for c in by_slot.get(s, ()) if c.gap_center is not None]
        if not gcs:
            return None, [f"jiazhu_step：段 {s0} 认不出缝，退回"]
        cx = int(round(float(np.median(gcs)))) - x_lo
        if not 4 <= cx <= w - 4:
            return None, [f"jiazhu_step：段 {s0} 缝贴边，退回"]
        if prev_end is None and use_head and s0 == 1 and out and all(c.slot <= 0 for c in out) \
                and _raised_is_note(ink, int(round(min(c.y0 for c in out))), top, cx, period):
            # v1.2：段从正文第 1 格起，格网却在上面多抬了一格（抬头格，常被列端判据记空）、那里的墨是两行小字：
            # 那是段的第一行，收回段里（02:58:8「臣｜令」）
            top = int(round(min(c.y0 for c in out)))
            out = []
            flags.append(f"jiazhu_head：段 1 收回列首抬头格（y={top}）")
        elif prev_end is None and use_head and not counts_ok:
            pre = sorted((c for c in out if c.kind != "blank"), key=lambda c: c.y0)
            ht = (_seg_head(ink, int(round(pre[0].y0)), len({c.slot for c in pre}), top, period)
                  if pre and len(pre) == len(out) else None)
            if ht is not None and abs(ht - top) >= HEAD_MIN_MOVE * period and pre and len(pre) == len(out) \
                    and ht - pre[0].y0 >= 0.5 * period * len({c.slot for c in pre}):
                top = ht
                head_moved = True
        end = _seg_end(ink, top, col_bot, cx, period)
        if (s0, m_a, m_b) == tuple(specs[-1]) and s0 + L - 1 >= last_slot:
            end = col_bot                     # v1.2：最后一段一直到列尾、下面没有正文格：段下沿就是列尾（02:17:3）
        elif end - top > SEG_GAP_TRY * L * period:
            e2 = _seg_end_fallback(ink, top, end, cx, L, period)
            if e2 is not None:
                flags.append(f"jiazhu_end_gap：段 {s0} 下沿按白行改到 y={e2}（原 {end}）")
                end = e2
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
        ends: dict[str, int] = {}
        for sub, m in (("a", m_a), ("b", m_b)):
            # 每行墨的末行：段下正文字起头 end 往上 END_MAX_DEPTH 格高以内起头的墨段是正文字探上来的笔画，跳过
            # 末段到列尾（v1.2）：下面没有正文字，不跳列尾的墨（02:134:8「火」）
            tail = i == len(plan) - 1 and s0 + L - 1 >= last_slot
            e = _line_end(rows[sub], top, end, end - END_MAX_DEPTH * period,
                          keep_h=TAIL_KEEP_H * period if tail else None)
            if e is None:
                return None, [f"jiazhu_step：段 {s0} {sub} 行找不到墨的末行，退回"]
            cuts = fit_row_cuts(rows[sub], top, e, m)
            if cuts is None or not _cuts_ok(ink, rows[sub], cuts, *spans[sub]):
                return None, [f"jiazhu_step：段 {s0} {sub} 行切不出 {m} 字，退回"]
            cuts_by[sub] = cuts
            ends[sub] = e
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
            q_ref, q_alt = _split_proven(ink, rows, spans, top, ends, m_a, m_b)
            # 段顶紧挨着格网别的夹注格（抬头 −1 格等）：段可能是从更上面起的，字数对不上段，格高匀也证明不了（03:90:3 备选格网）
            above = any(c.kind.startswith("jiazhu") and c.slot < s0 and c.y1 >= top - 0.2 * period
                        for c in cells if c.slot not in range(s0, s0 + L))
            if not above and q_ref <= UNEVEN_Q and q_alt >= q_ref + UNEVEN_MARGIN:
                flags.append(f"jiazhu_uneven_img:{s0}-{s0 + L - 1}：右 {m_a} 左 {m_b}（整理本分法），"
                             f"图上只有这种分法切得匀（{q_ref:.2f}，挪字 {q_alt:.2f}），不送审")
            else:
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
    if counts_ok and not _better(ink, x_lo, cells, new, specs):
        return None, []                       # v1.2：格数本来对、只因位置核不过才重切的列，新切法图上要更好才换（02:76:3）
    out += new
    for i, c in enumerate(reading_order(out) if reading_order else sorted(out, key=lambda c: c.slot), start=1):
        c.order = i
    return sorted(out, key=lambda c: (c.slot, c.kind)), flags


def apply(res, col_gray, content_x, period, specs, ink_threshold: int = 128, reading_order=None):
    """`RowBoundaryResult` 上做逐步切：成了换 cells、动过的夹注行格线跟着改（`_step_boundaries`），去掉动过的格的折线候选。返回 (res, 旗)。"""
    cells, flags = restep(res.cells, col_gray, content_x, period, specs, ink_threshold, reading_order)
    if cells is None:
        return res, flags
    s_min = min(s for s, _a, _b in specs)
    cands = [cp for cp in res.cut_candidates if cp.slot_below < s_min]
    n_raised = len({c.slot for c in res.cells if c.slot < 0})
    bounds = _step_boundaries(res.boundaries, cells, specs, n_raised)
    return (replace(res, cells=cells, cut_candidates=cands, boundaries=bounds),
            flags + ["jiazhu_step：按整理本分法逐步切"])


def _step_boundaries(bounds, cells, specs, n_raised: int = 0):
    """逐步切过的夹注行，格线（`boundaries`）改贴新切的 a/b 两半（v1.5，2026-11-06）。

    cell_shrink 把同 pos 的 a/b 合成满宽格时，两半 y 不同就取本格位的格线
    （`boundaries[pos-1]..boundaries[pos]`）当满宽格的上下沿，列端渣格闸也在这个框上判。
    逐步切只换 cells 不动格线，切满到列尾的段（第 16 轮 02:104:8 等六列第 21 行）格线落在字下的白里，
    满宽格判空、两半的字丢了。这里每行取两半的并（上沿取小、下沿取大），和上下邻行重叠的取中点；
    正文格（单格，cell_shrink 用它自己的 y）和没动的行不受影响。格位 pos = slot + 抬头格数（正文 slot 从 1 起）。
    """
    b = [float(x) for x in bounds]
    rows: dict[int, list[float]] = {}
    for c in cells:
        pos = c.slot + n_raised
        if (c.kind in ("jiazhu_a", "jiazhu_b") and c.slot > 0 and 0 < pos < len(b)
                and any(s0 <= c.slot < s0 + max(na, nb) for s0, na, nb in specs)):
            r = rows.setdefault(pos, [c.y0, c.y1])
            r[0], r[1] = min(r[0], c.y0), max(r[1], c.y1)
    for pos in sorted(rows):
        # 上沿：上一行也是逐步切的取两行之间的中点（不重叠），否则取本行两半的上沿；下沿留给下一行或取本行下沿
        b[pos - 1] = (rows[pos - 1][1] + rows[pos][0]) / 2.0 if pos - 1 in rows else rows[pos][0]
        if pos + 1 not in rows:
            b[pos] = rows[pos][1]
    for i in range(1, len(b)):  # 保单调
        b[i] = max(b[i], b[i - 1])
    return b
