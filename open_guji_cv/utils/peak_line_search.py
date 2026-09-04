"""投影峰匹配找版框线 — 界行/边框的另一把尺子。

跟 `border_detect.py`（LSD 检测线段 → 按共线性聚类）是完全不同的思路：
不找线段再拼，而是直接对墨迹做投影，找"又窄又尖"的峰。

## 算法

1. **投影**：竖直线（界行/左右边框）用逐列黑像素数（`mask.sum(axis=0)`）；
   水平线（上下边框）用逐行黑像素数（`mask.sum(axis=1)`）。
2. **半高宽匹配度**：对投影曲线上每个点 x，以它自己的值为基准，向左右各走到
   跌破自身一半（`alpha`）的位置为止（容忍 `<hyst` 个点的小凹陷，不算真跌出），
   两个边界之间的距离就是"半高宽"。**匹配度 = 投影值 ÷ 半高宽**：版框线又高又窄，
   比值大；正文字列虽然投影值也不低，但很宽，比值被拉得很低。
   宽度是每个点现算的，不用事先猜"这条线该多宽"。
3. **位置 + 角度联合搜索**：版框线可能有微小倾斜（原稿本身不完全垂直/水平，
   或裁切引入的残余倾斜），单纯竖直/水平投影会把斜线的峰"拖宽拖低"甚至完全看丢。
   对每个候选，允许峰的位置也跟着倾角一起变（重要：**不能把位置锁死在初始候选
   x₀ 上再单独搜角度**——峰的真实锚点会随倾角挪动，锁死位置等于把最优解排除在
   搜索范围外，这是本算法早期版本踩过的坑，参见 `.claude/doc/peak_line_search.md`）。
4. **性能优化**：a) 只在投影曲线自己的局部极大值上算半高宽分数，不用扫窗口里
   每个位置；b) 角度先粗后细两段扫（粗扫定位大致方向，细扫在附近精确定位），
   比一次性细扫全范围快，且因为最终分辨率更高，找到的分数往往还更高。

## 已知局限

- 位置搜索窗口需要卡在"跟相邻真实线的中点"，否则宽窗口搜索会越界抓到别的
  线（尤其页面文字密集时，宽范围搜索很容易被别的强峰"劫持"）。`find_vertical_lines`
  用相邻候选的中点自动切窗口；单独调用 `joint_search_coarse_to_fine` 时需要
  调用方自己控制窗口范围。
- 顶部边框在部分页面上信号本身就弱（磨损/浓墨粘连导致没有突兀尖峰，只有
  跟正文行同量级的宽驼峰），这种情况下即使方法本身没问题，找到的"最佳点"
  置信度也不如底部/竖直界行高——分数本身就能反映这一点，不需要额外判定。

详见 `.claude/doc/peak_line_search.md`（算法设计记录 + 踩过的坑 + 五页试跑结果）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_ALPHA = 0.5
DEFAULT_HYST = 3

# 联合搜索的采样窗口两侧各垫这么多 px（只用来量半高宽和两翼，候选峰仍限制在
# 原窗口内）。不垫的话，半高宽走到窗口边缘就被截断，切在文字驼峰上升沿的假峰
# 会拿到 4px 的"半高宽"和灌水的分数——vol01/42 左版框就是这样被第 9 列的字
# 顶掉的，全书 28/294 页有最终线正好压在窗口边界上。
SEARCH_PAD = 60
# 「版框/界行的投影是尖峰、两侧近乎为零；切到字上的峰两侧一定拖着字的墨」
# （用户 2026-09-03 给的判据）。两翼取半高宽外 [2, 12] px 里的最低值，跟峰高
# 的比 > FLANK_MAX_RATIO 就不是线。14 页金标 + 42/11 实测：158 条真线的比
# 中位 0.021、最大 0.23；两条已知假线 0.83（42 的文字峰）、0.43（11 的落字假线）。
FLANK_MAX_RATIO = 0.35
FLANK_GAP, FLANK_SPAN = 2, 10

# ── 最外侧两条线：粗外条 → 细内框的次候选 ──────────────────────
# 版框是"细内框 + 粗外条"。内框印得淡时，分数会输给粗外条，最外那条线就落在
# 外条上——列图因此多含一条 20px 的黑边、列宽偏大。全书 294 正文页里最外线
# 半高宽 >12 的有 19 页。
BAR_WIDTH_MIN = 12.0      # 半高宽超过这个就当"落在粗条上"，去朝页心一侧找内框。
                          # 健康页的细内框半高宽中位 5，19 页粗条是 13~21，中间空得很开。
INNER_GAP_MIN, INNER_GAP_MAX = 12.0, 78.0   # 内框离外条中心多远。**这不是拍的**：
                          # 90 页实测版框几何（measure_frame_geometry.py）里竖直外条
                          # 近沿 +20.4 / 远沿 +40.1（从内框线心往外量），条心约 +30；
                          # 19 页实测的间距 17~40、中位 30，跟它对得上——这是"细候选
                          # 确实是内框"的独立佐证，不是循环论证。区间沿用 border_geometry
                          # 的 OUTER_GAP_MIN/MAX。
INNER_WIDTH_MAX = 10.0    # 内框是细线；宽的是文字或另一条粗条，不收
INNER_PEAK_MIN = 0.035    # 沿线有墨的行占比下限。内框印得再淡也有 0.04~0.17；
                          # 低于这个就是噪声，宁可留在外条上（用户裁定：移到外框
                          # 远好过切到字上，但优先仍是内框）

# **这里不要开线程池**（2026-09-02 实测的负结果，别再加回来）。
# `sample_line_curve` 还是花式索引 gather 的时候，每个候选窗口的联合搜索有 98%
# 的时间在放开 GIL 的大数组运算上，4 线程能拿 2.2x。换成分块 BLAS 之后那部分
# 缩了 20 倍，剩下的时间大头变成**持 GIL 的 Python 循环**（每次调用约 150 个
# 分块、`half_height_score_at` 的 while、`local_maxima`），线程只剩争用：
# 14 页金标实测 串行 47.3s / 窗口 4 线程 59.8s / 窗口 2 线程 55.2s，**每一档都
# 是负收益**；BLAS 线程数（1 vs 4）对总时间没有区别（47.3 vs 47.8），说明这些
# gemv 太小、OpenBLAS 根本没多线程。
# 要并行就在**页级**（`ProcessPoolExecutor`，没有 GIL），见 regen_step2_columns.py。


# ── 半高宽匹配度 ──────────────────────────────────────────────


def projection(mask: np.ndarray, axis: str) -> np.ndarray:
    """axis='v': 逐列黑像素数（找竖直线用）；axis='h': 逐行黑像素数（找水平线用）。"""
    return mask.sum(axis=0) if axis == "v" else mask.sum(axis=1)


def half_height_score_at(curve: np.ndarray, idx: int,
                          alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST) -> tuple[float, float]:
    """对曲线上 idx 位置算半高宽和匹配度。返回 (半高宽, 匹配度=投影值/半高宽)。"""
    v = curve[idx]
    if v <= 0:
        return 0.0, 0.0
    thresh = v * alpha
    n = len(curve)

    def walk(start: int, step: int) -> int:
        pos, last_above, consec_below = start, start, 0
        while True:
            nxt = pos + step
            if nxt < 0 or nxt >= n:
                break
            if curve[nxt] >= thresh:
                last_above, consec_below = nxt, 0
            else:
                consec_below += 1
                if consec_below >= hyst:
                    break
            pos = nxt
        return last_above

    left = walk(idx, -1)
    right = walk(idx, 1)
    width = (right - left) + 1
    return float(width), float(v / width)


def full_sweep_scores(curve: np.ndarray, alpha: float = DEFAULT_ALPHA,
                       hyst: int = DEFAULT_HYST) -> tuple[np.ndarray, np.ndarray]:
    """对整条曲线逐点算半高宽/匹配度（初筛候选用；联合搜索内部不用这个，太慢）。"""
    n = len(curve)
    widths = np.zeros(n)
    scores = np.zeros(n)
    for i in range(n):
        wd, sc = half_height_score_at(curve, i, alpha, hyst)
        widths[i], scores[i] = wd, sc
    return widths, scores


def find_peaks_nms(scores: np.ndarray, min_dist: int, thresh: float) -> list[int]:
    """按分数从高到低贪心挑选，跳过跟已选点距离 < min_dist 的候选。"""
    idx_sorted = np.argsort(-scores)
    picked: list[int] = []
    for i in idx_sorted:
        if scores[i] < thresh:
            break
        if all(abs(int(i) - p) >= min_dist for p in picked):
            picked.append(int(i))
    return sorted(picked)


# ── 位置 + 角度联合搜索 ────────────────────────────────────────


def _shift_blocks(n_perp: int, slope: float) -> list[tuple[int, int, int]]:
    """把垂直方向的每一行/列按「整数位移相同」切成连续块，返回 [(a, b, k)]。

    位移 d = slope*(t - center) 在 t 上单调，所以 floor(d) 相同的 t 一定是一段
    连续区间——这正是分块采样成立的前提。|slope| <= 0.05、页高 ~3000 时块数
    约 150，远少于逐行的 3000 次。
    """
    t = np.arange(n_perp, dtype=np.float64)
    k = np.floor(slope * (t - n_perp / 2.0)).astype(np.int64)
    cuts = np.flatnonzero(np.diff(k)) + 1
    starts = np.concatenate(([0], cuts))
    ends = np.concatenate((cuts, [n_perp]))
    return [(int(a), int(b), int(k[a])) for a, b in zip(starts, ends)]


def sample_line_curve(mask: np.ndarray, axis: str, pos_lo: int, pos_hi: int,
                       slope: float) -> tuple[np.ndarray, np.ndarray]:
    """给定倾角，算一批候选位置(pos_lo..pos_hi)各自的倾斜投影值。

    axis='v'：position=x，直线 x = position + slope*(y - h/2)，逐 y 求和。
    axis='h'：position=y，直线 y = position + slope*(x - w/2)，逐 x 求和。
    越界坐标按 0（没有墨）处理，不外推复制边缘像素。

    **实现是分块 BLAS，不是花式索引**（2026-09-02 换的，采样本身快 19~24x）。
    朴素写法是建一个 `(n_pos, n_perp)` 的 `coord` 再 gather，元素个数是对的，
    但访存是随机的、而且要 9 个同样大的临时量。关键观察：对固定倾角，
    `coord[p, t] = p + slope*(t - center)`，**对 p 只是平移**——所以每一行要取的
    是一段**连续切片**；而整数位移相同的 t 是**连续区间**（`_shift_blocks`）。
    于是整幅 gather 拆成约 150 个「连续二维块 × 权重向量」的矩阵-向量乘，
    顺序访存 + BLAS。

    ⚠️ 求和次序跟朴素写法不同，投影值有 ~1e-12 的浮点差；`best_in_curve` 用
    严格 `>` 比分数，理论上能在极近的平局上翻面。14 页金标实测 `detect_borders`
    的全部输出逐位相同，但这不是结构性保证，改这段之后要重跑那套对拍。

    「加一维角度轴一次算完 60 档」是省不动的：元素个数一个不少，numpy 每次调用
    开销只有几十 us，60 次合起来 ~2ms，相对 16s 是噪声。省的必须是访存。
    """
    n_pos = pos_hi - pos_lo + 1
    if n_pos <= 0:                      # 空窗口，跟朴素实现一样返回空
        return np.arange(pos_lo, pos_hi + 1, dtype=np.float64), np.zeros(0)
    n_perp = mask.shape[0] if axis == "v" else mask.shape[1]
    limit = mask.shape[1] if axis == "v" else mask.shape[0]
    positions = np.arange(pos_lo, pos_hi + 1, dtype=np.float64)
    t = np.arange(n_perp, dtype=np.float64)
    frac = slope * (t - n_perp / 2.0)
    frac -= np.floor(frac)
    acc = np.zeros(n_pos)
    for a, b, k in _shift_blocks(n_perp, slope):
        # 有效条件 0 <= coord < limit-1，coord = p + k + frac 且 frac in [0,1)
        # <=> p + k 落在 [0, limit-2]
        p0 = max(0, -(pos_lo + k))
        p1 = min(n_pos, (limit - 1) - (pos_lo + k))
        if p1 <= p0:
            continue
        c0 = pos_lo + k + p0
        u = 1.0 - frac[a:b]
        v = frac[a:b]
        if axis == "v":
            acc[p0:p1] += u @ mask[a:b, c0:c0 + (p1 - p0)]
            acc[p0:p1] += v @ mask[a:b, c0 + 1:c0 + 1 + (p1 - p0)]
        else:
            acc[p0:p1] += mask[c0:c0 + (p1 - p0), a:b] @ u
            acc[p0:p1] += mask[c0 + 1:c0 + 1 + (p1 - p0), a:b] @ v
    return positions, acc


def _sample_line_curve_naive(mask: np.ndarray, axis: str, pos_lo: int, pos_hi: int,
                              slope: float) -> tuple[np.ndarray, np.ndarray]:
    """`sample_line_curve` 的朴素参考实现（花式索引），只留给对拍用，别在生产
    路径上调——比分块版慢 19~24x。"""
    h, w = mask.shape
    positions = np.arange(pos_lo, pos_hi + 1, dtype=np.float64)
    if axis == "v":
        perp = np.arange(h, dtype=np.float64)
        center = h / 2.0
        coord = positions[:, None] + slope * (perp[None, :] - center)
        limit = w
    else:
        perp = np.arange(w, dtype=np.float64)
        center = w / 2.0
        coord = positions[:, None] + slope * (perp[None, :] - center)
        limit = h

    valid = (coord >= 0) & (coord < limit - 1)
    coord_c = np.clip(coord, 0, limit - 1.001)
    i0 = np.floor(coord_c).astype(int)
    frac = coord_c - i0
    i1 = np.clip(i0 + 1, 0, limit - 1)
    perp_i = perp.astype(int)

    if axis == "v":
        v0, v1 = mask[perp_i, i0], mask[perp_i, i1]
    else:
        v0, v1 = mask[i0, perp_i], mask[i1, perp_i]

    vals = np.where(valid, v0 * (1 - frac) + v1 * frac, 0.0)
    return positions, vals.sum(axis=1)


def local_maxima(curve: np.ndarray, radius: int = 2) -> list[int]:
    """曲线上"半径内自己最大"的点，作为半高宽算法的候选（不用扫全部位置）。"""
    n = len(curve)
    if n == 0:
        return []
    # 窗口最大值一次算完：两端补 -inf 后 sliding_window_view，跟逐点切片取 max
    # 同一判据（2026-09-03 向量化，结果逐位相同）。原来是每次调用 O(n·radius)
    # 的 Python 循环，联合搜索每页调 1000+ 次。
    pad = np.concatenate([np.full(radius, -np.inf), curve, np.full(radius, -np.inf)])
    wmax = np.lib.stride_tricks.sliding_window_view(pad, 2 * radius + 1).max(axis=1)
    idx = [int(i) for i in np.flatnonzero((curve > 0) & (curve == wmax))]
    dedup: list[int] = []
    for i in idx:
        if dedup and i - dedup[-1] <= radius:
            if curve[i] > curve[dedup[-1]]:
                dedup[-1] = i
        else:
            dedup.append(i)
    return dedup


def flank_ratio(curve: np.ndarray, idx: int, width: float, sides: str = "both") -> float:
    """峰两翼的最低值 ÷ 峰高。翼取半高宽之外 [FLANK_GAP, FLANK_GAP+FLANK_SPAN] px。
    真线两翼是纸（≈0），切到字上的峰至少一侧拖着字。某一翼落在曲线外就当那翼
    未知（只看另一翼）。

    `sides`："both" / "left" / "right"（曲线下标方向）。**最外侧两个窗口只看朝
    页心那一翼**：外框是"细内框 + 粗外条"，内框朝外那一翼是外条的软边（离得
    只有十几 px），两翼都要求干净会把真内框闸掉——vol01/11 L1 就这么被换成
    了一条更平、离人工金标更远的线；而假峰（切在文字上）朝页心那一翼一定脏，
    只看那一翼照样拦得住（vol01/42 的文字峰朝页心翼 0.16 / 峰 0.18）。"""
    n = len(curve)
    a = int(round(width / 2.0))
    L = curve[max(0, idx - a - FLANK_GAP - FLANK_SPAN):max(0, idx - a - FLANK_GAP)]
    R = curve[min(n, idx + a + FLANK_GAP):min(n, idx + a + FLANK_GAP + FLANK_SPAN)]
    v = float(curve[idx])
    if v <= 0:
        return float("inf")
    parts = {"both": (L, R), "left": (L,), "right": (R,)}[sides]
    vals = [float(x.min()) for x in parts if len(x)]
    return max(vals) / v if vals else 0.0


def best_in_curve(curve: np.ndarray, alpha: float = DEFAULT_ALPHA,
                   hyst: int = DEFAULT_HYST, radius: int = 2,
                   idx_lo: int = 0, idx_hi: int | None = None,
                   flank_max_ratio: float | None = None,
                   flank_sides: str = "both") -> dict | None:
    """曲线上分数最高的峰。`idx_lo..idx_hi`（含）限制候选峰的位置——采样范围比
    候选范围两侧各宽 SEARCH_PAD，这样半高宽和两翼都能量完整。
    `flank_max_ratio` 给了就把两翼不干净的峰剔掉（见 FLANK_MAX_RATIO）。"""
    cands = local_maxima(curve, radius=radius)
    if idx_hi is None:
        idx_hi = len(curve) - 1
    best = None
    for i in cands:
        if i < idx_lo or i > idx_hi:
            continue
        wd, sc = half_height_score_at(curve, i, alpha, hyst)
        if flank_max_ratio is not None and flank_ratio(curve, i, wd, flank_sides) > flank_max_ratio:
            continue
        if best is None or sc > best["score"]:
            best = dict(idx=i, score=sc, width=wd, proj=float(curve[i]))
    return best


@dataclass
class LineMatch:
    position: float
    slope: float
    score: float
    width: float
    proj: float

    @property
    def angle_deg(self) -> float:
        return float(np.degrees(np.arctan(self.slope)))


def joint_search_coarse_to_fine(mask: np.ndarray, axis: str, pos_lo: int, pos_hi: int,
                                 coarse_range: float = 0.05, coarse_n: int = 35,
                                 fine_radius: float = 0.006, fine_n: int = 25,
                                 alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST,
                                 coarse_bank: tuple[int, dict[float, np.ndarray]] | None = None,
                                 flank_sides: str = "both") -> LineMatch:
    """位置 + 角度联合搜索：不把位置锁死在窗口中心，让峰的锚点跟角度一起找。

    先粗扫 ±coarse_range（coarse_n 档）定位大致倾角，再在附近 ±fine_radius
    精扫（fine_n 档）——两段合起来比一次性细扫全范围快，且因为最终分辨率
    更高，比固定粗网格找到的分数还更高。

    `coarse_bank=(bank_lo, {slope: curve})`：粗扫那 coarse_n 档倾角对同一页所有
    窗口都一样，而**投影值只跟位置和倾角有关、跟窗口无关**，所以整页可以
    每档只算一次（`coarse_curve_bank`），各窗口按位置切片。传了就用；精扫的
    倾角每个窗口不同，仍然现算。
    """
    best: dict | None = None

    # 垫窗口 + 两翼闸都只走竖直线。上下版框那条路一动就变：vol01/33 的真上框
    # （金标 517.9）会被换成 143px 外的抬头框——那边有自己的"更靠页心的次候选"
    # 逻辑和 14 页金标护着，这次不碰。
    pad = SEARCH_PAD if axis == "v" else 0
    lo_s, hi_s = pos_lo - pad, pos_hi + pad                    # 采样范围（垫过的）

    def take(s: float) -> tuple[np.ndarray, np.ndarray]:
        if coarse_bank is not None and s in coarse_bank[1]:
            bank_lo, curves = coarse_bank
            a = lo_s - bank_lo
            if a >= 0 and a + (hi_s - lo_s + 1) <= len(curves[s]):
                return (np.arange(lo_s, hi_s + 1, dtype=np.float64),
                        curves[s][a:a + (hi_s - lo_s + 1)])
        return sample_line_curve(mask, axis, lo_s, hi_s, s)

    def scan(slopes: np.ndarray) -> None:
        nonlocal best
        for s in slopes:
            positions, curve = take(float(s))
            b = best_in_curve(curve, alpha, hyst, idx_lo=pad, idx_hi=pad + (pos_hi - pos_lo),
                              flank_max_ratio=FLANK_MAX_RATIO if axis == "v" else None,
                              flank_sides=flank_sides)
            if b is None:
                continue
            rec = dict(slope=float(s), position=float(positions[b["idx"]]),
                       score=b["score"], width=b["width"], proj=b["proj"])
            if best is None or rec["score"] > best["score"]:
                best = rec

    scan(np.linspace(-coarse_range, coarse_range, coarse_n))
    if best is not None:
        scan(np.linspace(best["slope"] - fine_radius, best["slope"] + fine_radius, fine_n))

    if best is None:
        # 窗口里没有任何有墨的候选点——退化为窗口中心、零角度、零分
        center = (pos_lo + pos_hi) / 2.0
        return LineMatch(position=center, slope=0.0, score=0.0, width=0.0, proj=0.0)
    return LineMatch(**best)


def _snap_to_inner_rule(mask: np.ndarray, sel: LineMatch, center_side: str,
                        alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST) -> LineMatch:
    """最外侧那条线落在粗外条上时，改用朝页心一侧的细内框。

    只在 `sel.width > BAR_WIDTH_MIN` 时动手——健康页的最外线本来就是细内框
    （半高宽中位 5），一律原样返回。候选要同时满足：离外条 INNER_GAP_MIN~MAX、
    半高宽 <= INNER_WIDTH_MAX、朝页心那一翼干净、沿线墨占比 >= INNER_PEAK_MIN。
    多个满足就取**最靠外**的那条（离外条最近）——内框只有一条，更靠里的是界行。

    `center_side` 是朝页心的翼方向（"right"=页左那条线，"left"=页右那条线），
    跟 `find_vertical_lines` 里给 `flank_sides` 的值一致。
    """
    if sel.width <= BAR_WIDTH_MIN or sel.score <= 0:
        return sel
    h, w = mask.shape
    step = 1 if center_side == "right" else -1        # 曲线下标朝页心的方向
    i0 = int(round(sel.position))
    lo = min(i0, i0 + step * int(INNER_GAP_MAX))
    hi = max(i0, i0 + step * int(INNER_GAP_MAX))
    lo, hi = max(0, lo - SEARCH_PAD), min(w - 1, hi + SEARCH_PAD)
    if hi - lo < 2 * SEARCH_PAD:
        return sel
    positions, curve = sample_line_curve(mask, "v", lo, hi, sel.slope)
    best = None
    for i in local_maxima(curve):
        gap = (positions[i] - sel.position) * step
        if not (INNER_GAP_MIN <= gap <= INNER_GAP_MAX):
            continue
        wd, sc = half_height_score_at(curve, i, alpha, hyst)
        if wd > INNER_WIDTH_MAX or curve[i] / h < INNER_PEAK_MIN:
            continue
        if flank_ratio(curve, i, wd, center_side) > FLANK_MAX_RATIO:
            continue
        if best is None or gap < best[0]:             # 最靠外的那条
            best = (gap, LineMatch(position=float(positions[i]), slope=sel.slope,
                                   score=sc, width=wd, proj=float(curve[i])))
    return sel if best is None else best[1]


def coarse_curve_bank(mask: np.ndarray, axis: str, pos_lo: int, pos_hi: int,
                      coarse_range: float = 0.05, coarse_n: int = 35
                      ) -> tuple[int, dict[float, np.ndarray]]:
    """粗扫那组倾角在 [pos_lo, pos_hi] 上的投影曲线，整页一次算齐。
    键是跟 `joint_search_coarse_to_fine` 里 `np.linspace` 同一组 float，切片时
    按键精确匹配。"""
    curves = {}
    for s in np.linspace(-coarse_range, coarse_range, coarse_n):
        _, c = sample_line_curve(mask, axis, pos_lo, pos_hi, float(s))
        curves[float(s)] = c
    return pos_lo, curves


# ── 整页便捷入口 ──────────────────────────────────────────────


def _windows_from_candidates(candidates: list[int], lo_bound: int, hi_bound: int,
                              margin_lo: int, margin_hi: int) -> list[tuple[int, int]]:
    """候选位置排序后，用相邻中点切窗口——避免宽范围搜索越界抓到邻居的线。"""
    windows = []
    for i, c in enumerate(candidates):
        lo = int(round((candidates[i - 1] + c) / 2)) + 1 if i > 0 else lo_bound - margin_lo
        hi = int(round((c + candidates[i + 1]) / 2)) if i < len(candidates) - 1 else hi_bound + margin_hi
        windows.append((lo, hi))
    return windows


def _dedup_by_position(results: list[LineMatch], min_dist: int) -> list[LineMatch]:
    """按分数从高到低贪心保留，跳过离已保留结果 < min_dist 的——见
    `find_vertical_lines` 里"窗口切在同一条真实线中间"那段注释。"""
    ordered = sorted(results, key=lambda r: -r.score)
    deduped: list[LineMatch] = []
    for r in ordered:
        if all(abs(r.position - k.position) >= min_dist for k in deduped):
            deduped.append(r)
    return deduped


def find_vertical_lines(mask: np.ndarray, min_dist: int = 60, nms_percentile: float = 90,
                         edge_margin: int = 200, expected_count: int | None = None,
                         alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST) -> list[LineMatch]:
    """整页竖直线（左右边框 + 内部界行）一次性找齐，按 x 从小到大排序。

    先用整页列投影 + 半高宽全扫找候选峰位置（NMS 去重，`min_dist` 建议设成比
    真实线宽大一个数量级、比列距小——默认 60px 是经验值，太小会把同一条线
    的相邻局部峰重复收进来），再对每个候选做位置+角度联合精搜——窗口卡在
    相邻候选的中点，最左/最右两条各往页面外留 `edge_margin` px（版框线的
    真实位置可能跟粗投影找到的候选差几十像素，需要留够搜索空间，参见文档
    里 x=33/216 的案例）。

    粗筛之后可能还会剩下几个弱的假候选（文字笔画凑巧对齐产生的次级峰）。
    如果知道这一页应该有几列，传 `expected_count`（跟 `border_detect.py`
    里 `expected_cols` 的用法一致）——按匹配度只留分数最高的 N 条，比猜一个
    通用阈值更稳。不传的话把所有候选原样返回，由调用方按分数自行判断。
    """
    h, w = mask.shape
    curve = projection(mask, "v")
    _, scores = full_sweep_scores(curve, alpha, hyst)
    thresh = float(np.percentile(scores, nms_percentile))
    candidates = find_peaks_nms(scores, min_dist, thresh)
    if not candidates:
        return []

    windows = _windows_from_candidates(candidates, 0, w - 1, edge_margin, edge_margin)
    # 粗扫 35 档倾角整页只算一次再按窗口切片：原来 17 个窗口 × 35 档 = 595 次
    # `sample_line_curve`，其中两个边缘窗口 600+px 宽还跟中间窗口重叠。
    bank = coarse_curve_bank(mask, "v", windows[0][0] - SEARCH_PAD, windows[-1][1] + SEARCH_PAD)
    results = []
    for k, (lo, hi) in enumerate(windows):
        # 曲线下标 = 旧坐标 x 递增；最左窗口朝页心是右翼，最右窗口是左翼
        sides = "right" if k == 0 else ("left" if k == len(windows) - 1 else "both")
        r = joint_search_coarse_to_fine(mask, "v", lo, hi, alpha=alpha, hyst=hyst,
                                        coarse_bank=bank, flank_sides=sides)
        if sides != "both":
            r = _snap_to_inner_rule(mask, r, sides, alpha, hyst)
        results.append(r)

    # 相邻粗候选切出的窗口有时会切在同一条真实线中间——两侧窗口各自精修
    # 都收敛到这条线上，位置只差十几到几十像素，是精修阶段"两个窗口找到
    # 同一条线"的重复（不是前面 NMS min_dist 不够大导致的候选级重复）。
    # 不去重的话，这种重复会在 expected_count 按分数截断时把两个名额都占
    # 走，挤掉别处一条本该收进来的真实列线（vol01/141 col8 实测复现：x≈1633
    # 和x≈1648两个窗口各出一条线，双双挤进前10，页面最右一条真实列线被
    # 顶掉）。用跟前面候选级 NMS 相同的间距假设去重（真实列距远大于 min_dist）。
    results = _dedup_by_position(results, min_dist)

    if expected_count is not None and len(results) > expected_count:
        results = results[:expected_count]

    results.sort(key=lambda r: r.position)
    return results


def find_horizontal_border(mask: np.ndarray, side: str, band_frac: float = 0.15,
                            alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST,
                            secondary_window: int = 60, secondary_dead_zone: int = 15,
                            secondary_ratio_thresh: float = 0.2) -> LineMatch:
    """找页面顶部或底部的边框线（side='top'/'bottom'）。

    只在页面顶/底 `band_frac` 比例的窄带内搜——上下边框不像竖直界行那样有
    "相邻线"的概念，直接限定在页边margin区域内找最强峰即可。

    带内全局分数最高的峰不一定是真正的内边框：抬头页顶部的抬头装饰墨迹
    分数有时比边框本身还高（vol01/49），底部有时会锁到外边框而不是内
    边框（vol01/137、138）。这两种情况有个共同点——真正的内边框物理上
    总是比这些干扰峰更靠近页面中心（装饰墨迹在边框外/上方，外边框在
    纸边更外侧）。所以先按原逻辑找 `primary`（保证所有已经正确的页面不
    受影响），再只在 `primary` 位置附近 ±`secondary_window` px 的窄窗口内
    （不能扩大到整个条带——之前试过带内多候选+相对分数阈值+"离中心最近"
    的方案，结果远处噪声峰把好几个本来正确的页面带崩了，见
    `.claude/doc/peak_line_search.md`）找一个"比 primary 更靠近页面中心、
    且匹配度达到 primary 一定比例"的候选，找到就换成它，否则保留 primary。
    """
    h, w = mask.shape
    band = max(10, int(h * band_frac))
    if side == "top":
        lo, hi = 0, band
    else:
        lo, hi = h - band, h - 1

    primary = joint_search_coarse_to_fine(mask, "h", lo, hi, alpha=alpha, hyst=hyst)

    center = h / 2.0
    primary_dist = abs(primary.position - center)
    wlo = max(lo, int(round(primary.position)) - secondary_window)
    whi = min(hi, int(round(primary.position)) + secondary_window)
    positions, curve = sample_line_curve(mask, "h", wlo, whi, primary.slope)

    best_secondary: dict | None = None
    for i in local_maxima(curve, radius=5):
        pos = float(positions[i])
        if abs(pos - primary.position) < secondary_dead_zone:
            continue
        if abs(pos - center) >= primary_dist:
            continue
        wd, sc = half_height_score_at(curve, i, alpha, hyst)
        if primary.score <= 0 or sc / primary.score <= secondary_ratio_thresh:
            continue
        if best_secondary is None or sc > best_secondary["score"]:
            best_secondary = dict(position=pos, score=sc, width=wd, proj=float(curve[i]))

    if best_secondary is None:
        return primary
    return LineMatch(position=best_secondary["position"], slope=primary.slope,
                      score=best_secondary["score"], width=best_secondary["width"],
                      proj=best_secondary["proj"])
