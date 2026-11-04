"""于千子干 拆笔画判（zy，2026-11-01 A24「区分于千子干的笔画判法」，判法是 sheldon 定的）。

只吃字块灰度图，不看上下文。分三步，每步量不清就弃权（交文意，文意也定不了才送人审）：

1. **竖有没有钩**：字块下 25% 行里，竖画左侧的墨量（以竖宽×行数归一）。于子有钩，千干没有。
2. **于／子：两横之间那一段**是直的短竖（于），还是从右上斜下来的一撇（子，乛 的折笔）。
   从顶上第一段宽行（首笔）之下到长横上沿，每行取离竖最近的一段墨的中点，量 x 对 y 的斜率 `dxdy`
   与顶部比底部偏右多少个竖宽 `off`。
3. **千／干：首笔**。取长横以上、与长横隔一段空行的连通块，每列只取从上往下第一段墨（不带竖），
   竖那几列按左右两边的上下沿连起来，补成完整一横；去掉两头（右端 25% 是衬线），量中线斜率 `k`
   （往右上升为负，千的首笔是一撇）；另量首笔右端三角凸起高出主体上沿多少个笔粗 `bump`（干的横右端在宋体下有凸起）。

门槛是拿 dataset `char-groups/variant/zy/shape40`（sheldon 确认的 40 例）定的，间隔都留了余量；
字块把首笔裁掉、竖找不准时一律弃权。只在候选与整理本字都落在于千子干里时跑（`registry` 用 `Only` 包着）：
予 也有钩、也有斜撇，不能交给它判。
"""
from __future__ import annotations

import numpy as np

#: 门槛：先拿 shape40（sheldon 确认 40 例）看判法，再拿 vol20–99 ★main 已放行 2,688 格按册（奇偶册互为留出）定，见模块尾注
HOOK_YES = 0.13       # 竖左侧下部墨量 ≥ 此值 → 有钩
HOOK_NO = 0.01        # ≤ 此值 → 没钩；两者之间弃权
ZI_GAP = 2            # 竖顶与首笔之间、竖那几列空 ≥ 此行数 → 子（于 的竖一路通到首笔，全是 0）
YU_DXDY = 0.15        # 于：竖那几列不空（gap=0），且两横之间那段直：|斜率| ≤ 此值、
YU_OFF = (-0.15, 0.2)  # 顶部比底部偏右（竖宽）落在此区间
QIAN_K = -0.08        # 首笔斜率 ≤ 此值 → 千（往右上升为负）
QIAN_K_MIN = -0.4     # 比这还陡是首笔没取对（字块上沿切进别的笔画），弃权
GAN_K = -0.02         # 干：首笔平（斜率 ≥ 此值）
GAN_BUMP = 0.8        #     且右端凸起 ≥ 此值（个笔粗）；千 也有首笔平、右端翘的，0.6 会把 千 判成 干
MIN_ASPECT = 0.6      # 字块宽／高（或高／宽）小于此值是切坏的块，弃权


def binarize(gray) -> np.ndarray:
    import cv2
    g = np.asarray(gray)
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    if g.dtype != np.uint8:
        g = g.astype(np.uint8)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b > 0


def drop_frame(b: np.ndarray) -> np.ndarray:
    """列尾格常把边框线收进字块（vol27:73:9:21、vol85:16:4:21）：上下 15% 里横贯 85% 字块宽的细行抹掉，免得当成钩。"""
    H, W = b.shape
    b = b.copy()
    for y in list(range(int(.15 * H) + 1)) + list(range(int(.85 * H), H)):
        xs = np.flatnonzero(b[y])
        if len(xs) and len(xs) >= 0.85 * W and xs.max() - xs.min() >= 0.85 * W:
            b[y] = False
    return b


def clean(b: np.ndarray, keep: float = 0.25) -> np.ndarray | None:
    """去掉小于最大连通域 `keep` 倍的墨块（噪点、邻字残笔），裁到外框。"""
    import cv2
    n, lab, st, _ = cv2.connectedComponentsWithStats(b.astype(np.uint8), connectivity=8)
    if n < 2:
        return None
    a = st[1:, cv2.CC_STAT_AREA]
    m = np.isin(lab, 1 + np.flatnonzero(a >= keep * a.max()))
    ys, xs = np.where(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def stem_cols(b: np.ndarray) -> tuple[int, int]:
    """竖画左右边：只看字块下 40%（那里只有竖），列墨量最大的一段。"""
    H, W = b.shape
    low = b[int(.6 * H):].sum(0).astype(float)
    c = int(low.argmax())
    l = r = c
    while l > 0 and low[l - 1] > 0.3 * low.max():
        l -= 1
    while r < W - 1 and low[r + 1] > 0.3 * low.max():
        r += 1
    return l, r


def long_bar(b: np.ndarray, l: int, r: int) -> tuple[int, int]:
    """长横：竖以外墨量最多的一行（20%–75% 高度），返回 (该行, 上沿)。"""
    H, _ = b.shape
    out = b.copy()
    out[:, l:r + 1] = False
    cnt = out.sum(1)
    lo, hi = int(.2 * H), max(int(.2 * H) + 1, int(.75 * H))
    bar = lo + int(cnt[lo:hi].argmax())
    bt = bar
    while bt > 0 and cnt[bt - 1] >= 0.35 * cnt[bar]:
        bt -= 1
    return bar, bt


def hook(b: np.ndarray) -> float:
    """竖左侧下部墨量。竖按整列墨量定（下部取竖会把钩算进竖宽里）。"""
    import cv2
    H, W = b.shape
    cs = cv2.blur(b.sum(0).astype(float)[None, :], (3, 1))[0]
    c = int(cs.argmax())
    l = r = c
    while l > 0 and cs[l - 1] > 0.5 * cs.max():
        l -= 1
    while r < W - 1 and cs[r + 1] > 0.5 * cs.max():
        r += 1
    m = b.copy()
    m[:, max(0, l - 2):r + 3] = False
    hb = int(.75 * H)
    return float(m[hb:, :l].sum()) / max(1, (r - l + 1) * (H - hb))


def mid_segment(b: np.ndarray, l: int, r: int, bt: int) -> dict:
    """两横之间那一段：中点斜率 dxdy、顶部偏右 off（竖宽）、行数 n。"""
    rows = np.flatnonzero(b.any(1))
    t0, sw = int(rows.min()), r - l + 1
    wide = [y for y in range(t0, bt) if b[y].sum() >= 2.5 * sw]
    if not wide:
        y = t0 + 2                        # 首笔被裁掉：从顶往下取
    else:
        y = wide[0]
        while y + 1 < bt and b[y + 1].sum() >= 2.5 * sw:
            y += 1
        y += 1
    # 从长横上沿往上追：每行取与下一行那段相接（或最近）的一段，子 的折笔能一路追到右上
    c = (l + r) / 2
    # 折笔与竖的接口常印断（vol20:2:6:6b）：接不上时允许往右跳半个竖宽、跳过至多 2 行空白
    pts, miss = [], 0
    for yy in range(bt - 1, y - 1, -1):
        xs = np.flatnonzero(b[yy])
        runs = np.split(xs, np.flatnonzero(np.diff(xs) > 1) + 1) if len(xs) else []
        if pts:
            px0, px1 = pts[-1][2], pts[-1][3]
            touch = [q for q in runs if q.min() <= px1 + 1 and q.max() >= px0 - 1] or \
                [q for q in runs if q.min() <= px1 + max(2, sw // 2) and q.max() >= px0 - 1]
            if not touch:
                miss += 1
                if miss > 2:
                    break
                continue
            miss = 0
            run = max(touch, key=len)
        elif len(runs):
            run = min(runs, key=lambda q: abs(q.mean() - c))
        else:
            break
        pts.append((yy, run.mean(), run.min(), run.max()))
    pts = [(p[0], p[1]) for p in pts[::-1]]
    out = {"n": len(pts), "gap": stem_gap(b, l, r, bt)}
    if len(pts) < 5:
        return out
    P = np.array(pts)
    return {**out, "dxdy": float(np.polyfit(P[:, 0], P[:, 1], 1)[0]),
            "off": float((P[:3, 1].mean() - P[-3:, 1].mean()) / sw)}


def stem_gap(b: np.ndarray, l: int, r: int, bt: int) -> int | None:
    """首笔与长横之间，竖画那几列（按长横上沿处的竖中心 ±1/3 竖宽）有几行是空的。
    于 的竖一路通到首笔，0 行；子 的竖顶在折笔下面，竖顶与首笔之间只有右边斜下来的折笔，竖那几列空着。"""
    rows = np.flatnonzero(b.any(1))
    t0, sw = int(rows.min()), r - l + 1
    wide = [y for y in range(t0, bt) if b[y].sum() >= 2.0 * sw]
    if not wide:
        return None
    y = wide[0]
    while y + 1 < bt and b[y + 1].sum() >= 2.0 * sw:
        y += 1
    y0 = y + 1
    if bt - y0 < 5:
        return None
    cs = []
    for yy in range(bt - 3, bt):
        xs = np.flatnonzero(b[yy])
        if len(xs):
            runs = np.split(xs, np.flatnonzero(np.diff(xs) > 1) + 1)
            cs.append(min(runs, key=lambda q: abs(q.mean() - (l + r) / 2)).mean())
    if not cs:
        return None
    cb, h = float(np.mean(cs)), max(1, sw // 3)
    return int((~b[y0:bt, max(0, int(cb - h)):int(cb + h) + 1].any(1)).sum())


def first_stroke(b: np.ndarray, l: int, r: int, bt: int) -> np.ndarray | None:
    """千干首笔：长横上沿以上、与长横隔一段空行的最大连通块，去掉竖、补成完整一横。"""
    import cv2
    H, W = b.shape
    out = b.copy()
    out[:, l:r + 1] = False
    cnt = out.sum(1)
    y = bt - 1
    while y > 0 and cnt[y] <= 2:
        y -= 1
    if y <= 0:
        return None
    reg = np.zeros_like(b)
    reg[:y + 1] = b[:y + 1]
    n, lab, st, _ = cv2.connectedComponentsWithStats(reg.astype(np.uint8), connectivity=8)
    if n < 2:
        return None
    m = lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    L, R = l - 1, r + 1
    edges = {}
    for x in range(W):
        if L <= x <= R:
            continue
        ys = np.flatnonzero(m[:, x])
        if len(ys):
            run = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)[0]
            edges[x] = (int(run.min()), int(run.max()))
    left = sorted(x for x in edges if x < L)
    right = sorted(x for x in edges if x > R)
    if not left or not right:
        return None
    S = np.zeros_like(b)
    for x, (t, bb) in edges.items():
        S[t:bb + 1, x] = True
    tl, bl = np.median([edges[x][0] for x in left[-3:]]), np.median([edges[x][1] for x in left[-3:]])
    tr, br = np.median([edges[x][0] for x in right[:3]]), np.median([edges[x][1] for x in right[:3]])
    xl, xr = left[-1], right[0]
    for x in range(xl + 1, xr):
        f = (x - xl) / (xr - xl)
        S[int(round(tl + (tr - tl) * f)):int(round(bl + (br - bl) * f)) + 1, x] = True
    return S


def stroke_slope(S: np.ndarray, trim: float = 0.25) -> float | None:
    xs = [x for x in range(S.shape[1]) if S[:, x].any()]
    n = len(xs)
    xs = xs[2:n - max(2, int(trim * n))]
    if len(xs) < 6:
        return None
    c = [(np.flatnonzero(S[:, x]).min() + np.flatnonzero(S[:, x]).max()) / 2 for x in xs]
    return float(np.polyfit(xs, c, 1)[0])


def right_bump(S: np.ndarray, r: int) -> float | None:
    """首笔右半：右端 30% 列的最高点高出主体上沿多少个笔粗。"""
    cols = [x for x in range(r + 1, S.shape[1]) if S[:, x].any()]
    if len(cols) < 6:
        return None
    top = np.array([np.flatnonzero(S[:, x]).min() for x in cols], float)
    bot = np.array([np.flatnonzero(S[:, x]).max() for x in cols], float)
    th = float(np.median(bot - top + 1))
    k = max(2, int(.3 * len(cols)))
    return float((np.median(top[:len(cols) - k]) - top[len(cols) - k:].min()) / th)


def judge(gray) -> tuple[str | None, str, dict]:
    """→ (于／千／子／干 或 None, 原因, 量值)。"""
    b0 = drop_frame(binarize(gray))
    b = clean(b0) if b0.any() else None
    if b is None or min(b.shape) < 12:
        return None, "abstain:no_ink", {}
    if min(b.shape) / max(b.shape) < MIN_ASPECT:
        return None, "abstain:aspect", {"shape": list(b.shape)}
    l, r = stem_cols(b)
    _, bt = long_bar(b, l, r)
    f: dict = {"hook": round(hook(b), 3)}
    if f["hook"] >= HOOK_YES:
        f.update({k: (round(v, 3) if isinstance(v, float) else v) for k, v in mid_segment(b, l, r, bt).items()})
        # 只认「竖那几列空没空」分 于子：两横之间那段的斜率只作 于 的佐证。于 的首笔右端常往右上翘，
        # 从长横往上追会一路追进首笔右半、量成斜撇（vol56:110:7:21「古夫于」），所以斜撇不单独判 子。
        gap = f.get("gap")
        straight = "dxdy" in f and abs(f["dxdy"]) <= YU_DXDY and YU_OFF[0] <= f["off"] <= YU_OFF[1]
        if gap is not None and gap >= ZI_GAP:
            return "子", "agree", f
        if gap == 0 and straight:
            return "于", "agree", f
        return None, "abstain:mid" if gap is not None else "abstain:no_mid", f
    if f["hook"] > HOOK_NO:
        return None, "abstain:hook", f
    S = first_stroke(b, l, r, bt)
    if S is None:
        return None, "abstain:no_first", f
    k, bump = stroke_slope(S), right_bump(S, r)
    f.update({"k": None if k is None else round(k, 3), "bump": None if bump is None else round(bump, 2)})
    if k is None:
        return None, "abstain:no_first", f
    if QIAN_K_MIN <= k <= QIAN_K and (bump is None or bump < 0.6):
        return "千", "agree", f
    if k >= GAN_K and bump is not None and bump >= GAN_BUMP:
        return "干", "agree", f
    return None, "abstain:first", f
