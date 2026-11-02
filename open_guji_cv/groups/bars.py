"""量横长短后端（M7 扩展第二阶段）：土士、未末这类「两横一长一短」的字组，看字块图上两横谁长。

下横/上横 > 1 ＝ 土、未；< 1 ＝ 士、末；离 1 不足 `margin`（缺省 0.1）或取不到两横则弃权。
只吃字块灰度图（`cell.patch`），不看上下文；与文意路各自出 pick，合并由调用方（`seed_admit` 接线时）按
「文意有字用文意、文意弃权才按量横、两路不一致打旗」做。缺图抛 `PatchUnavailable`，不静默弃权。
量法细节与评测见 `doc/design/M7-字形量横画法-土士未末.md`、`research/m7/bars/`。

另有一二（yr）的**数横**（`count_bars`，2026-10-25 A24）：一一横、二两横（上短下长、上下对齐），切进邻字的残笔、
印章噪点、列尾的边框线都弃权。见 `doc/字组/yr.md`。

本模块只是库代码：未登记进 `registry`、未接任何 Step，`code_hash` 不变。
"""
from __future__ import annotations

import numpy as np

from .protocol import GroupVerdict, JudgeInput, PatchUnavailable

#: 组 id → (下横长的字, 上横长的字)
PAIRS = {"ts": ("土", "士"), "wm": ("未", "末")}

_GAP = 8          # 横画内容许的白缝（刻印断口）
_BAR_FRAC = 0.3   # 一行里最长连续墨 > 此比例×字宽才算横画行


def _cv2():
    import cv2
    return cv2


def _main_cc(ink: np.ndarray) -> np.ndarray | None:
    """横向膨胀后取最大连通域（把被竖画或断口断开的横画连回来），返回裁到外框的墨掩码。"""
    cv2 = _cv2()
    k = cv2.dilate(ink.astype(np.uint8), np.ones((5, 25), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(k)
    if n < 2:
        return None
    m = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))) & ink
    ys, xs = np.where(m)
    if len(ys) == 0:
        return None
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _longest_run(row: np.ndarray, gap: int) -> int:
    xs = np.flatnonzero(row)
    if len(xs) == 0:
        return 0
    best, s, p = 0, xs[0], xs[0]
    for x in xs[1:]:
        if x - p - 1 > gap:
            best, s = max(best, p - s + 1), x
        p = x
    return max(best, p - s + 1)


def _bands(m: np.ndarray) -> list[tuple[int, int, int]]:
    L = np.array([_longest_run(r, _GAP) for r in m])
    on = L > _BAR_FRAC * m.shape[1]
    out, y = [], 0
    while y < len(on):
        if on[y]:
            y0 = y
            while y < len(on) and on[y]:
                y += 1
            out.append((y0, y - 1, int(L[y0:y].max())))
        else:
            y += 1
    return out


def bar_ratio(gray: np.ndarray) -> float | None:
    """下横/上横。取最长两条横带按 y 排序，长度＝带内墨的最左到最右。取不到两横 → None。"""
    cv2 = _cv2()
    g = np.asarray(gray)
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    if g.dtype != np.uint8:
        g = g.astype(np.uint8)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    m = _main_cc(b > 0)
    if m is None:
        return None
    bands = _bands(m)
    if len(bands) < 2:
        return None
    top2 = sorted(sorted(bands, key=lambda z: -z[2])[:2], key=lambda z: z[0])
    ext = []
    for y0, y1, _ in top2:
        cols = np.flatnonzero(m[y0:y1 + 1].any(0))
        ext.append(int(cols.max() - cols.min() + 1))
    return ext[1] / ext[0]


class BarsImageBackend:
    name = "image"
    fingerprint = ""

    def __init__(self, margin: float = 0.1):
        self.margin = margin

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        if spec.id not in PAIRS:
            return GroupVerdict(None, why="abstain:no_pair", via="image")
        if cell.patch is None:
            raise PatchUnavailable(cell.id)
        r = bar_ratio(cell.patch())
        if r is None:
            return GroupVerdict(None, why="abstain:no_bars", via="image", extra={"ratio": None})
        if abs(r - 1) < self.margin:
            return GroupVerdict(None, conf=abs(r - 1), why="abstain:close", via="image", extra={"ratio": r})
        bottom_long, top_long = PAIRS[spec.id]
        return GroupVerdict(bottom_long if r > 1 else top_long, conf=abs(r - 1), why="agree", via="image",
                            extra={"ratio": r})


# —— 一二数横（yr，2026-10-25 A24「优化一二判别」） ——
#
# 字块是格内墨的外接框（「一」的字块本来就扁）。墨按连通域收，竖向重叠过半的连通域并成一条「横带」；
# 够长（≥0.3×字块宽）且扁（长 ≥2.5×厚）的横带算一横。门槛是拿殿本 vol04–20 已放行的 7,545 格定的
# （量出来的字与放行字 0 不一致；量横弃权的 397 格逐格看过图），判不清一律弃权：
# - 横以外的墨 > 15%（印章噪点、切进来的邻字）→ 弃权；
# - 一：横外墨 ≤ 5%、横带够实（墨占外接框 ≥18%、最长一段 ≥ 带长一半）、中段没有竖起的小笔
#   （中段最厚处／中位厚 ≤3：「有」「六」「主」被切开时上半是一横加一点或一竖，vol15:97:1:3、vol17:112:5:6 都被放成过「一」）；
# - 二：两横上下对齐（上横中点落在下横 20%–85%）、都够实、下横不短于上横的 0.9 倍且墨不少于上横的 0.8 倍
#   （列尾格常把边框线收进来：一＋边框线是上重下轻），下横贴底又薄于上横 0.6 倍也算边框线；
# - 三横以上 → 弃权。
# 量横只认字块里的笔画：字块本身切错（「無一不謬」的格切进了「不」的上横，vol19:116:9:8）它也会跟着错，
# 所以 yr 流程里它不单独定结论（见 `registry` 的 yr）。

YR_OTHER_MAX = 0.15
YR_ONE_OTHER_MAX = 0.05
YR_FILL_MIN = 0.18
YR_SOLID_MIN = 0.5
YR_BUMP_MAX = 3.0


def yr_bands(gray: np.ndarray) -> list[dict]:
    """字块 → 横带列表（自上而下）：每条记外接框（占字块宽高的比例）、墨占全字比 `ink`、墨占外接框比 `fill`、
    最长连通段占带长比 `solid`、中段竖向最厚／中位厚 `bump`、是否算一横 `bar`。"""
    cv2 = _cv2()
    g = np.asarray(gray)
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    if g.dtype != np.uint8:
        g = g.astype(np.uint8)
    H, W = g.shape
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b)
    comps, tot = [], 0
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if a >= max(4, 0.002 * H * W):                  # 去掉零星噪点
            comps.append([y, y + h, x, x + w, a, w, [i]])
            tot += a
    comps.sort(key=lambda c: (c[0] + c[1]) / 2)
    bands: list[list] = []
    for c in comps:                                     # 竖向重叠过半 → 同一条横带（断开的横画、顿笔）
        for bb in bands:
            if min(bb[1], c[1]) - max(bb[0], c[0]) >= 0.5 * min(bb[1] - bb[0], c[1] - c[0]):
                bb[0], bb[1], bb[2], bb[3] = min(bb[0], c[0]), max(bb[1], c[1]), min(bb[2], c[2]), max(bb[3], c[3])
                bb[4] += c[4]
                bb[5] = max(bb[5], c[5])
                bb[6] += c[6]
                break
        else:
            bands.append([*c[:6], list(c[6])])
    out = []
    for y0, y1, x0, x1, a, wmax, ids in bands:
        col = np.isin(lab[y0:y1, x0:x1], ids).sum(0).astype(float)    # 每列竖向墨厚
        w = x1 - x0
        mid = col[int(0.2 * w):max(int(0.2 * w) + 1, int(0.75 * w))]
        med = float(np.median(col[col > 0])) if (col > 0).any() else 0.0
        out.append(dict(y0=y0 / H, y1=y1 / H, x0=x0 / W, x1=x1 / W, len=w / W, thick=(y1 - y0) / H,
                        ink=a / max(tot, 1), fill=a / max(1, w * (y1 - y0)), solid=wmax / max(1, w),
                        bump=float(mid.max()) / med if med > 0 else 0.0,
                        bar=w >= 0.3 * W and w >= 2.5 * (y1 - y0)))
    out.sort(key=lambda s: s["y0"])
    return out


def count_bars(gray: np.ndarray) -> tuple[str | None, str]:
    """一二数横 → (「一」|「二」|None, 理由)。理由：one／two，或弃权原因（other_ink、one_other_ink、one_sparse、
    one_bump、off_center、sparse、top_heavy、border、n<横数>）。"""
    bands = yr_bands(gray)
    bars = [s for s in bands if s["bar"]]
    other = sum(s["ink"] for s in bands if not s["bar"])
    if other > YR_OTHER_MAX:
        return None, "other_ink"
    if len(bars) == 1:
        a = bars[0]
        if other > YR_ONE_OTHER_MAX:
            return None, "one_other_ink"
        if a["fill"] < YR_FILL_MIN or a["solid"] < YR_SOLID_MIN:
            return None, "one_sparse"
        if a["bump"] > YR_BUMP_MAX:
            return None, "one_bump"
        return "一", "one"
    if len(bars) == 2:
        a, b = bars
        c = ((a["x0"] + a["x1"]) / 2 - b["x0"]) / b["len"]
        if not 0.2 <= c <= 0.85:
            return None, "off_center"
        if min(a["fill"], b["fill"]) < YR_FILL_MIN:
            return None, "sparse"
        if b["len"] < 0.9 * a["len"] or b["ink"] < 0.8 * a["ink"]:
            return None, "top_heavy"
        if b["y1"] >= 0.95 and b["thick"] < 0.6 * a["thick"]:
            return None, "border"
        return "二", "two"
    return None, f"n{len(bars)}"


# —— 十士 数横（ss，2026-11-01 A24「压低剩余 V 与 N 类送审」） ——
#
# 十＝一横一竖，士＝两横一竖。字块里先取横向膨胀后的最大连通域（把被竖画断开的横连回来），逐行找最长连续墨，
# 够长（≥0.45×字块宽）的行成带：一条带、横下面的竖还有 ≥30% 字高、带不厚（<25% 字高）→ 十；
# 两条带、中间留白 ≥12% 字高 → 士；其余弃权。殿本已放行的 23,246 格（十 17,316、士 5,930；vol20–99 抽 3,000）
# 单独量横错 0.4%，错的全是列尾格把栏框线收进来当了第二横（十量成士）；所以只当「证据」用，补放须整理本也同意（`lift_ref_agree`）。
SS_FRAC = 0.45
SS_BELOW_MIN = 0.3
SS_THICK_MAX = 0.25
SS_GAP_MIN = 0.12


def ss_count(gray: np.ndarray) -> tuple[str | None, str]:
    """十士数横 → (「十」|「士」|None, 理由)。理由：one／two，或弃权原因（nomain、one_odd、two_close、n<横数>）。"""
    cv2 = _cv2()
    g = np.asarray(gray)
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    if g.dtype != np.uint8:
        g = g.astype(np.uint8)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    m = _main_cc(b > 0)
    if m is None:
        return None, "nomain"
    H, W = m.shape
    L = np.array([_longest_run(r, _GAP) for r in m])
    on = L > SS_FRAC * W
    bands, y = [], 0
    while y < H:
        if on[y]:
            y0 = y
            while y < H and on[y]:
                y += 1
            bands.append((y0, y - 1))
        else:
            y += 1
    if len(bands) == 1:
        y0, y1 = bands[0]
        if (H - 1 - y1) / H >= SS_BELOW_MIN and (y1 - y0 + 1) < SS_THICK_MAX * H:
            return "十", "one"
        return None, "one_odd"
    if len(bands) == 2:
        if (bands[1][0] - bands[0][1]) >= SS_GAP_MIN * H:
            return "士", "two"
        return None, "two_close"
    return None, f"n{len(bands)}"
