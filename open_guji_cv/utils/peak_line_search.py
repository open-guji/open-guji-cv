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
- `flank_dirty_frac`（2026-09-12 新增）：诊断"候选线是否多次穿过字体"的
  分段两翼干净度，68 页金标上跟像素误差确实正相关，但拿它改
  `find_horizontal_border` 的候选排序/否决在整体指标上都是负收益，**没有
  接入自动选线逻辑**，只作为诊断量导出——细节和试过的几种失败整合方式见
  函数自身的 docstring。

详见 `.claude/doc/peak_line_search.md`（算法设计记录 + 踩过的坑 + 五页试跑结果）。
"""

from __future__ import annotations

from collections import Counter
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


FLANK_SEG_STEP = 40    # 分段宽度：粗于单字笔画（几像素）、细于列距（180~250px），
                       # 让每段大致对应"半个字到一个字"的尺度
FLANK_SEG_DIRTY_TH = 0.05  # 单段两翼墨占比超过这个就算这段"脏"


def flank_dirty_frac(mask: np.ndarray, y: int, width: float, w: int,
                     step: int = FLANK_SEG_STEP, gap: int = FLANK_GAP, span: int = FLANK_SPAN,
                     dirty_th: float = FLANK_SEG_DIRTY_TH) -> float:
    """诊断量"沿候选水平线多次穿过字体"（2026-09-12 新增，用户任务卡原话）：
    把 `flank_ratio` 的"看两翼干不干净"从整条线只测 1~2 个点，改成沿整条线
    切成 `step` px 的小段、每段各自测两翼——真实版框线是一条贯穿全页的连续
    印刷直线，理论上沿线各处两翼都该是纸白；如果候选线实际上是"多列文字
    恰好在同一高度对齐"拼出来的假峰，则只有恰好压中字尾的那几段两翼干净，
    其余大多数段的两翼都会因为紧挨着字身而"脏"。返回"两翼脏的分段"占比，
    越高越像文字对齐拼出来的假线，越低越像连续印刷直线。

    ## 实测结论（68 页金标）：相关但不足以单独当判据，没有接入 `find_horizontal_border`

    68 页金标上量过：这个值跟"算法最终结果的像素误差"确实正相关
    （Pearson r≈0.26；按中位数分两组，dirty_frac 高的一组平均误差 22.0px，
    低的一组 8.8px）——**方向是对的，是真信号，不是噪声**。

    但拿它做候选重排/否决都试过，68 页整体指标不升反降：
    - 直接用 `score * (1-dirty)^p` 重排候选（替换现有次选纠偏的纯分数比较）：
      p=1~3 全部让 68 页 mean 从 12.3px 涨到 21.6~21.8px，>20px 页数 41→63。
    - 只加一条"候选比 primary 更脏就否决"的护栏（不改排序，只加否决）：
      margin 0~0.3 全部让指标变差或持平（最松的 margin=0.3 也只是 12.32→12.45，
      >20px 页数 41→43，没有一档是净改善）。
    - 只在候选分数"接近平局"时用它当 tie-break（更保守的用法）：
      margin 0.05~0.5 全部跟 baseline 持平或略差，从没有更好。

    原因：真实的版框线一旦磨损到需要救的程度（这批 40 页正是"次选纠偏已经
    在生效但换到的候选本身不够准"那批），它自己的墨迹也是断续的（跟假峰
    一样"多次穿过"），这个判据的 68 页中位数分组差异虽然存在，但落到具体
    某一页时区分度不够稳定（同一页假峰可能比真线还"干净"，见 vol02/68：
    err=(29.4,22.6) 但 longest_run_frac=0.76，比大多数正确页还高）。

    **结论：先留作诊断量（暴露给上层做人工复核/跨页一致性分析用），不接入
    `find_horizontal_border` 的自动选线逻辑**——这条路目前证明是死路，跟
    `.claude/doc/peak_line_search.md` 记录的"扩窗口/降阈值"是同一类教训：
    单页内的几何判据已经吃干榨尽，下一步大概率要靠跨页先验（同一本书同一
    版式，真实版框位置应该聚在窄范围内）才可能破局。
    """
    n_perp = mask.shape[0]
    a = int(round(width / 2.0))
    dirty, total = 0, 0
    for x0 in range(0, w, step):
        x1 = min(w, x0 + step)
        left = mask[max(0, y - a - gap - span):max(0, y - a - gap), x0:x1]
        right = mask[min(n_perp, y + a + gap):min(n_perp, y + a + gap + span), x0:x1]
        l_ratio = float(left.mean()) if left.size else 0.0
        r_ratio = float(right.mean()) if right.size else 0.0
        total += 1
        if max(l_ratio, r_ratio) > dirty_th:
            dirty += 1
    return dirty / total if total else 0.0


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
    results, _ = _vline_pool(mask, min_dist, nms_percentile, edge_margin, alpha, hyst)
    if not results:
        return []

    if expected_count is not None and len(results) > expected_count:
        results = results[:expected_count]

    results.sort(key=lambda r: r.position)
    return results


def _vline_pool(mask: np.ndarray, min_dist: int, nms_percentile: float, edge_margin: int,
                alpha: float, hyst: int
                ) -> tuple[list[LineMatch], tuple[int, dict[float, np.ndarray]] | None]:
    """`find_vertical_lines` 截断之前的候选池：粗筛 → 逐窗口联合精搜 → 去重。
    返回 (按分数降序的候选, 粗扫曲线库)。`find_vertical_lines` 与
    `find_vertical_lines_grid` 共用这一段，前者的行为逐位不变。"""
    h, w = mask.shape
    curve = projection(mask, "v")
    _, scores = full_sweep_scores(curve, alpha, hyst)
    thresh = float(np.percentile(scores, nms_percentile))
    candidates = find_peaks_nms(scores, min_dist, thresh)
    if not candidates:
        return [], None

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
    return _dedup_by_position(results, min_dist), bank


# ── 网格模式：列数已知、列距均匀 → 逐槽验线、缺槽补线 ──────────────────
# 北行日錄刻本（灰度扫描、筒子页 9+版心+9 = 19 列）实测：全书 972 个界行槽位里
# 120 个（12.3%）**根本没印出界行**（p41 左半叶整片空白，只有右半叶有线；54 页里
# 只有 15 页界行齐全）。自由模式按分数取前 N 条时，这些槽位只能拿字身竖向对齐的
# 假峰凑数（半高宽 50+px、分数 ~10），而 `expected_cols` 多写 1 又逼它每页收一条
# 页边。四庫總目那批是 1-bit 双色扫描，界行条条实黑，从来没有「槽位空着」这回事，
# 所以自由模式在 14 页金标上中位误差 0.05px——不是算法坏了，是这本书缺线。
#
# 网格模式的做法：版框两条线定死，列距 = 框宽 / (N−1)，每个槽位只在 ±GRID_SLOT_TOL
# 里做位置+角度联合精搜；找不到细线（分数低于 GRID_MIN_SCORE，或半高宽超过
# GRID_MAX_WIDTH）就按相邻已验线**线性插值**，并把该槽标成 filled。于是每条线要么是
# 验过的细线、要么是几何插值——永远不会落在字上。
GRID_SLOT_TOL = 18       # px。p20/p41 实测等距网格离真线最多 7~9px，留一倍余量；
                         # 再大就够到字身边缘（栏缝约 40px 宽）
GRID_MIN_SCORE = 20.0    # 半高宽匹配分。同书实测：真界行 27~222、字身假峰 ~10、空槽 ~1
GRID_MAX_WIDTH = 12.0    # 细线；字身假峰半高宽 50+。与 INNER_WIDTH_MAX 同量级
GRID_PITCH_TOL = 0.08    # 版框对的隐含列距与 col_pitch 的容差（逐页列距实测 p10–p90 ±2%）


def find_vertical_lines_grid(mask: np.ndarray, n_lines: int, col_pitch: float | None = None,
                             *, slot_tol: int = GRID_SLOT_TOL, min_score: float = GRID_MIN_SCORE,
                             max_width: float = GRID_MAX_WIDTH,
                             pitch_tol_frac: float = GRID_PITCH_TOL,
                             min_dist: int = 60, nms_percentile: float = 90,
                             edge_margin: int = 200,
                             alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST
                             ) -> tuple[list[LineMatch], list[bool]]:
    """列数已知（`n_lines` = 列数 + 1）、列距均匀的页：返回恰好 `n_lines` 条线
    （按 x 升序）和同长度的 `filled` 标记（True = 该槽位没探到细线、按几何插值）。

    1. 版框对：候选池里两两配对，隐含列距 (b−a)/(n_lines−1) 与 `col_pitch` 差在
       `pitch_tol_frac` 内（没给 `col_pitch` 就只要求列距 ≥ min_dist）；按「有多少
       槽位落着细线」排，同分再按两条线的投影和排——版框是整页最实的两条竖线，
       页边那条假线（北行日錄 54/54 页都有）隐含列距不对、支持数也低，选不上。
    2. 逐槽：在 `a + k·pitch ± slot_tol` 里 `joint_search_coarse_to_fine`（两翼都要干净），
       分数 ≥ `min_score` 且半高宽 ≤ `max_width` 才算探到。
    3. 缺槽：相邻已验线（含版框）之间线性插值位置和斜率，`score/width/proj` 记 0。

    ⚠️ `n_lines` 必须是这本书的真值——写错了网格整体错位，任何一槽都验不上，
    最后全靠插值（闸2 会看到列宽异常）。北行日錄刻本曾把 expected_cols 写成 20
    （实际 19），就是这种情况。
    """
    if n_lines < 2:
        raise ValueError(f"n_lines must be >= 2, got {n_lines}")
    pool, bank = _vline_pool(mask, min_dist, nms_percentile, edge_margin, alpha, hyst)
    if len(pool) < 2:
        pool.sort(key=lambda r: r.position)
        return pool, [False] * len(pool)
    h, w = mask.shape
    n_gap = n_lines - 1
    thin = [r for r in pool if 0.0 < r.width <= max_width and r.score >= min_score]

    def support(a: LineMatch, b: LineMatch) -> int:
        p = (b.position - a.position) / n_gap
        return sum(1 for k in range(1, n_gap)
                   if any(abs(r.position - (a.position + k * p)) <= slot_tol for r in thin))

    best: tuple[tuple[int, float], LineMatch, LineMatch] | None = None
    for a in pool:
        for b in pool:
            span = b.position - a.position
            if span <= 0:
                continue
            p = span / n_gap
            if col_pitch is not None:
                if abs(p - col_pitch) > pitch_tol_frac * col_pitch:
                    continue
            elif p < min_dist:
                # 列距不可能小于候选 NMS 间距（相邻两条线本来就会被合掉）。
                # 别写成 2×min_dist：那会把 119px 的列距（北行日錄）直接拒掉。
                continue
            key = (support(a, b), a.proj + b.proj)
            if best is None or key > best[0]:
                best = (key, a, b)
    if best is None:
        # 没有任何一对满足列距约束——版框本身没探到，退回自由模式的截断，
        # 让闸1 按列数拒掉这一页
        pool = pool[:n_lines]
        pool.sort(key=lambda r: r.position)
        return pool, [False] * len(pool)

    _, a, b = best
    a = _snap_to_inner_rule(mask, a, "right", alpha, hyst)
    b = _snap_to_inner_rule(mask, b, "left", alpha, hyst)
    left, right = a.position, b.position
    pitch = (right - left) / n_gap

    lines: list[LineMatch | None] = [a] + [None] * (n_gap - 1) + [b]
    filled = [False] * n_lines
    for k in range(1, n_gap):
        c = left + k * pitch
        lo, hi = max(0, int(round(c - slot_tol))), min(w - 1, int(round(c + slot_tol)))
        r = joint_search_coarse_to_fine(mask, "v", lo, hi, alpha=alpha, hyst=hyst,
                                        coarse_bank=bank, flank_sides="both")
        if r.score >= min_score and 0.0 < r.width <= max_width:
            lines[k] = r
        else:
            filled[k] = True

    known = [i for i in range(n_lines) if lines[i] is not None]
    for i in range(n_lines):
        if lines[i] is not None:
            continue
        j = max(x for x in known if x < i)
        k = min(x for x in known if x > i)
        lj, lk = lines[j], lines[k]
        t = (i - j) / (k - j)
        lines[i] = LineMatch(position=lj.position + t * (lk.position - lj.position),
                             slope=lj.slope + t * (lk.slope - lj.slope),
                             score=0.0, width=0.0, proj=0.0)
    return [ln for ln in lines if ln is not None], filled


def find_horizontal_border(mask: np.ndarray, side: str, band_frac: float = 0.15,
                            alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST,
                            secondary_window: int = 60, secondary_dead_zone: int = 15,
                            secondary_ratio_thresh: float = 0.2,
                            boundary_slack: int = 3,
                            verticals: list[LineMatch] | None = None,
                            book_gap: float | None = None) -> LineMatch:
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

    **搜索带边界锁死**（2026-09-12 补，vol03/7、vol02/26 实测，仅 `bottom`）：
    `primary` 精确落在搜索带跟页面中心那一侧的边界上，本身就是退化信号——
    真实版框线被截断带外/带内更深处，这不是"探到了这个位置"，是搜索窗口
    边缘的伪影（常见于文字异常贴近页边、把带边界切进了密集文字里）。这种
    情况下"更靠近中心才可信"的护栏毫无意义（primary 本来就不可信，没有
    "偏"这回事可防），改成直接在整条搜索带内找最强的非边界峰当新 primary，
    再按原逻辑走后续的次选纠偏。

    **只对 `side="bottom"` 生效**：`side="top"` 试过同一逻辑，vol01/33
    实测直接踩雷——那页抬头，主版框恰好也贴近带边界触发这条修复，但整带
    内最强的非边界峰是抬头装饰墨迹（比主版框墨更浓更粗），结果从"差不多
    对"的主版框换成了错误的抬头墨迹，正中"更靠中心才可信"这条护栏本来
    要防的那个坑（`vol01/49` 那一类）。顶部的边界锁死交给
    `detect_head_raise` 那条专门链路处理，不在这里碰。
    """
    h, w = mask.shape
    band = max(10, int(h * band_frac))
    if side == "top":
        lo, hi = 0, band
        inner_edge = hi
    else:
        lo, hi = h - band, h - 1
        inner_edge = lo

    primary = joint_search_coarse_to_fine(mask, "h", lo, hi, alpha=alpha, hyst=hyst)

    if side == "bottom" and abs(primary.position - inner_edge) <= boundary_slack:
        positions, curve = sample_line_curve(mask, "h", lo, hi, primary.slope)
        best_full: dict | None = None
        for i in local_maxima(curve, radius=5):
            pos = float(positions[i])
            if abs(pos - inner_edge) <= boundary_slack:
                continue
            wd, sc = half_height_score_at(curve, i, alpha, hyst)
            if best_full is None or sc > best_full["score"]:
                best_full = dict(position=pos, score=sc, width=wd, proj=float(curve[i]))
        if best_full is not None:
            primary = LineMatch(position=best_full["position"], slope=primary.slope,
                                score=best_full["score"], width=best_full["width"],
                                proj=best_full["proj"])

    if verticals:
        primary = _fix_wild_angle(mask, primary, verticals, lo, hi, alpha, hyst)

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
        result = primary
    else:
        result = LineMatch(position=best_secondary["position"], slope=primary.slope,
                           score=best_secondary["score"], width=best_secondary["width"],
                           proj=best_secondary["proj"])

    if side == "bottom" and verticals and book_gap is not None:
        result = _rescue_bottom(mask, result, verticals, book_gap, alpha, hyst)
        # 先按页把线挪到墨条下沿（详见 `_descend_to_ink_bottom` 上方说明），
        # 再让一个很小的固定余量补判定口径的不对称（往下无害、往上切字）。
        lo2 = max(0, int(round(result.position)) - EDGE_MAX_WALK)
        hi2 = min(h - 1, int(round(result.position)) + EDGE_MAX_WALK * 2)
        pos2, curve2 = sample_line_curve(mask, "h", lo2, hi2, result.slope)
        if len(curve2):
            i0 = int(np.clip(round(result.position) - lo2, 0, len(curve2) - 1))
            i1 = _descend_to_ink_bottom(curve2, i0)
            result = LineMatch(position=float(pos2[i1]), slope=result.slope,
                               score=result.score, width=result.width,
                               proj=result.proj)
        result = LineMatch(position=result.position + BOTTOM_SAFETY_MARGIN,
                           slope=result.slope, score=result.score,
                           width=result.width, proj=result.proj)
    return result


# ── 角度失控护栏：版框该大致垂直于界行 ──────────────────────────
# `joint_search_coarse_to_fine` 在 ±0.05 的斜率范围内自由搜角度，**完全不看
# 界行**。2400px 宽的页上 0.05 的斜率差 = 端点摆动 120px，所以一旦搜飞，
# 一端安全另一端就深切进字里。vol02/161 实测：算法选了 -0.04706（几乎顶到
# 搜索边界），而界行垂直方向是 +0.00782——**符号相反、大小差 6 倍**，端点
# 张口 123px。用正确角度重投影后，带内最强候选分 31.6，比它选中那条（9.3）
# 强 3 倍多：投影法没问题，是角度自由度害的。
#
# ⚠️ **只能是软约束，不能强制垂直**（186 页实测）：偏角 >1° 的 20 页里有
# **19 页算法与金标偏得分毫不差、端点张口 0px**（vol02/120 双方都 -1.74°、
# vol03/6 都 +1.31°…）——这套书的版框本来就不严格垂直于界行（刻版、纸张
# 变形），算法跟着实际版框走是对的。强制垂直会把张口中位数从 0.0 抬到
# 14.3px、p90 从 13.6 抬到 39.5px，把大批正确页弄坏。
#
# 所以阈值取 2.5°：金标偏角实测最大 1.74°，2.5° 拦得住 161 的 3.21°，
# 又碰不到那 19 页真实倾斜的页。186 页实测：**只改动 1 页**
# （vol02/161 从 -61.4 修成 +23.1），其余 185 页逐位不变。
WILD_ANGLE_MAX_DEG = 2.5
_WILD_ANGLE_STEPS = 41


def _fix_wild_angle(mask: np.ndarray, primary: LineMatch, verticals: list[LineMatch],
                    lo: int, hi: int, alpha: float, hyst: int) -> LineMatch:
    """primary 的倾角偏离「界行垂直方向」太多时，在合理角度窗内重搜一条。"""
    if len(verticals) < 2:
        return primary
    perp = -float(np.median([v.slope for v in verticals]))
    dev_deg = abs(np.degrees(np.arctan(primary.slope)) - np.degrees(np.arctan(perp)))
    if dev_deg <= WILD_ANGLE_MAX_DEG:
        return primary
    lim = float(np.tan(np.radians(WILD_ANGLE_MAX_DEG)))
    best: tuple[float, float, float, float, float] | None = None
    for s in np.linspace(perp - lim, perp + lim, _WILD_ANGLE_STEPS):
        _, curve = sample_line_curve(mask, "h", lo, hi, float(s))
        for i in local_maxima(curve, radius=5):
            y = lo + i
            if abs(y - lo) <= 3 or abs(y - hi) <= 3:      # 带边界退化值
                continue
            wd, sc = half_height_score_at(curve, i, alpha, hyst)
            if best is None or sc > best[2]:
                best = (float(y), float(s), sc, wd, float(curve[i]))
    if best is None:
        return primary
    y, s, sc, wd, proj = best
    return LineMatch(position=y, slope=s, score=sc, width=wd, proj=proj)


# ── 下版框跨页先验救援 ────────────────────────────────────────────
# 上面那套（primary + 次选纠偏 + 边界锁死）在 68 页整页坐标金标上仍有约 1/3
# 的页误差 >20px：真线得分被文字驼峰压过，而**峰形本身分不开真假**——68 页
# 实测金标峰与"远处最强假峰"在绝对宽(5~120 vs 4~92)、相对宽、墨浓度、峰顶
# 平坦度四个量上完全重叠，浓度和平坦度甚至反向。所以不可能靠加一条局部判据
# 解决，只能引入这一页之外的信息。
#
# 能分开的只有**跨页一致性**：同一册同一版式，下版框离页底的距离极稳定——
# 三册金标实测 `页高 - y` 的 std 只有 6.3/8.8px，中位数 325/327/326px 高度
# 一致；而算法逐页输出的 std 是 24~26px。于是"这一页偏离全册中位数多少"
# （dev）就是一个可靠的可疑信号，且**生产时不需要金标**：整册算法输出的
# 中位数与金标真基准只差 0~1px（vol02 完全相等）。
#
# 救援动作用三条判据重搜（都是用户 2026-09-12 给的方向，逐条实测过）：
#   1. **跳开左右竖边框拐角**：拐角处墨团会灌水分数。只用最外两条竖线之间
#      再各内缩 RESCUE_MARGIN 的区域投影。
#   2. **界行垂直方向作先验角度**：竖线斜率取反即水平线斜率，只在其 ±0.006
#      内微调。自由搜角实测更差（68 页 mean 39.7 vs 29.1）。
#   3. **只看下翼干净**：下版框上方紧挨正文末行，上翼本来就脏，要求两翼都
#      干净会把真线闸掉（vol02/60 真线下翼 0.48、vol02/22 0.62 都会被误杀）。
#      每档宽度上限下 "只看下翼" 都胜过 "两翼都要"。
#
# 两条护栏，缺一不可：
#   - **落点必须在基准邻域内**（RESCUE_GUARD_D）。vol03/25 实测：真线 y=2745
#     （分 15.3、离金标 5px）输给弱候选 y=2815（分仅 1.0）纯因为后者在更多
#     斜率档上出现、票数多（21:6）。加了这条护栏后 D=25~60 全都选回 y=2745，
#     对 D 不敏感——是有原则的修法，不是调参。不加护栏则 68 页上必有 1 页
#     被改坏，加了之后弄坏 0。
#   - **宽度上限 RESCUE_WMAX 不能放宽**。放宽到 20/30/60/120 即使有护栏也
#     全面变差（救回 8→4→2、弄坏 0→3→4），因为粗文字驼峰会在别的页上赢走。
#     代价是真线本身就是粗墨条的页救不回来（vol02/64 真线宽 113、vol02/70
#     宽 108），这是本方法有据可依的天花板。
#
# 68 页金标实测（per-endpoint）：mean 12.3→8.4、p90 34.5→24.4、max 110.8→42.9、
# >20px 41→28，救回 8、弄坏 0；困难子集 mean 20.8→13.0。
# ⚠️ 下面这组常数 2026-09-13 按**单侧口径**重调过（原先按对称像素误差调的
# 25/40 是另一套目标）。186 页金标实测（TOL=30，"高于金标即切字，不给容差"）：
#   现状            切字 49 / 过 136 / 太低 1
#   本组常数        切字 34 / 过 144 / 太低 8   （修好 17、弄坏 2）
# 弄坏的 2 页里 vol02/181 只挪了 1px（浮点边界，无实际影响），真正改差的只有
# vol02/94（现役 +13.6 → 重搜选了更强但更远的峰）。
RESCUE_DEV_MIN = 15.0     # 偏离全册基准超过这么多才出手。单侧口径下 25 太保守：
                          # 22 页切字页的 dev 落在 15~25，够不着救援；放到 15
                          # 多修 5 页。再往下到 10 则"太低"从 8 涨到 20，不划算。
RESCUE_SELF_OK_SCORE = 100.0   # 现役线自身分数达到这个就不动它。**dev 大不等于
                          # 错**：vol02/175 dev=44 却完全正确（worst=-0.0），
                          # vol02/55（分190）、112（分150）同理。加这条后弄坏
                          # 从 5 页压到 2 页，是这组常数里最关键的一条。
RESCUE_DOWN_ONLY = True   # 重搜结果不许比现役更靠上（用户原则：宁可留白不可切字）
RESCUE_MARGIN = 45        # 最外竖线再往内缩多少，避开拐角墨团
RESCUE_WMAX = 14.0        # 候选半高宽上限，见上"不能放宽"
RESCUE_FLANK_MAX = 0.5    # 只测下翼（页边空白那侧）的脏度上限
RESCUE_GUARD_D = 80.0     # 落点离基准推算位置的最大距离。单侧口径下从 40 放到
                          # 80：往下多留白无害，卡太紧反而挡掉真线（实测 80 比
                          # 60 多修 2 页，弄坏不变）。
RESCUE_SLOPE_SPAN = 0.006
RESCUE_SLOPE_N = 25

# ── 安全余量：探到线之后整体再往下让一点 ──────────────────────────
# 用户的口径是**不对称**的："宁肯再往下一点，留点空白或污点，也绝不要靠上，
# 切到最后一个字。" 而算法是**对称**地去拟合墨条中心的——186 页实测，
# |算法−金标|<15px 的 140 页里 median=+0.0、mean=-0.1、std=2.1px：
# **没有系统性偏移，算法平均就压在金标上**。问题恰恰在这里：既然散布 std≈2px
# 而零点就在切字边缘上，那必然有一半左右的页会掉到上方去。
#
# 所以不该去追"压得更准"，而应该整体让出一点余量。186 页实测：
#   余量 0 → 切字 33 / 过 145 / 太低 8
#   余量 6 → 切字 18 / 过 156 / 太低 12   ← 拐点
#   余量 8 → 切字 15 / 过 155 / 太低 16
#   余量10 → 切字 13 / 过 151 / 太低 22（过反而开始跌，不划算）
# 取 6：切字直接砍掉近一半，代价只是 4 页从"过"变成"留白略多"。
#
# ⚠️ 这是**下版框专用**，且只在 `book_gap` 已标定（即启用救援）时生效——
# 它补的是"判定口径不对称"，不是"算法有偏"。`side="top"` 不适用：上版框
# 往下让等于切掉首行字，方向正好相反。
BOTTOM_SAFETY_MARGIN = 6.0


# ── 下版框锚到墨条下沿 ────────────────────────────────────────
# 2026-09-13：金标修正后重看 7 页深切字（vol02/64,70,71,79,93,155,182），
# 病因完全一致：**算法把线压在墨条的上沿，而人标的是下沿**。投影峰的
# 「顶点」落在墨条中部偏上，可下版框的语义是「正文到此为止」——墨条整条
# 都属于版框，所以该取它的**下**边缘。
#
# 这也解释了 `BOTTOM_SAFETY_MARGIN=6` 为什么不够：墨条实测厚 25~50px，
# 6px 补不过一整条。而且加大余量是**全局**的，会把本来就落在下沿的正确页
# 一起推进空白里（实测 B=10 时"过"反而从 156 跌到 151）。
#
# 正确做法是**按页自适应**：从峰位沿曲线往下走，走到墨结束的地方。墨条薄
# 的页自然只挪几 px，厚的页挪几十 px，不需要一个放之四海的常数。
#
# `EDGE_ALPHA` 比 `DEFAULT_ALPHA`(0.5) 低：半高(0.5)还在墨条内部，要的是
# 墨真正淡下去的位置，所以取 0.25。`EDGE_MAX_WALK` 封顶，防止在"墨条下面
# 紧跟着书口脏迹"的页上一路滑下去。
EDGE_ALPHA = 0.25
EDGE_MAX_WALK = 60
EDGE_HYST = 3


def _descend_to_ink_bottom(curve: np.ndarray, idx: int,
                           alpha: float | None = None,
                           max_walk: int | None = None,
                           hyst: int | None = None) -> int:
    """从峰位 `idx` 沿曲线往下走到墨条下沿，返回新的下标（>= idx）。

    判据跟 `half_height_score_at` 的 `walk` 同构（连续 `hyst` 个点低于阈值
    才算出界），但阈值更低、且**只往下**走。找不到更下沿就原地返回。

    ⚠️ 三个参数默认 `None`、在**函数体里**取模块常数，不能写成
    `alpha: float = EDGE_ALPHA` 那样的默认值——默认值在 def 执行时就绑死了，
    调参脚本改 `P.EDGE_ALPHA` 根本传不进来。2026-09-13 的扫描就栽在这上面：
    四档 alpha 跑出**逐字节相同**的结果，白跑一轮才发现是这个坑。
    """
    alpha = EDGE_ALPHA if alpha is None else alpha
    max_walk = EDGE_MAX_WALK if max_walk is None else max_walk
    hyst = EDGE_HYST if hyst is None else hyst
    v = float(curve[idx])
    if v <= 0:
        return idx
    thresh = v * alpha
    n = len(curve)
    pos, last_above, consec_below = idx, idx, 0
    while pos - idx < max_walk:
        nxt = pos + 1
        if nxt >= n:
            break
        if curve[nxt] >= thresh:
            last_above, consec_below = nxt, 0
        else:
            consec_below += 1
            if consec_below >= hyst:
                break
        pos = nxt
    return last_above


def _rescue_bottom(mask: np.ndarray, cur: LineMatch, verticals: list[LineMatch],
                   book_gap: float, alpha: float, hyst: int) -> LineMatch:
    """现役结果偏离全册基准太多时，用跨页先验重搜一条。详见上方大段说明。

    **单侧口径**（用户 2026-09-13 定）："宁肯再往下一点，留点空白或污点，
    也绝不要靠上，切到最后一行字。" 所以两条约束：
      1. `RESCUE_DOWN_ONLY`：重搜结果不许比现役更靠上——往上一点就切字，
         往下只是多留白。186 页实测，这条把"弄坏"从 8 页压到 4 页。
      2. `RESCUE_SELF_OK_SCORE`：现役线自身够强就不动它。**"偏离全册基准"
         不等于错**——vol02/175 的 dev 高达 44 却完全正确（worst=-0.0），
         vol02/55/112 同理。加这条后"弄坏"再从 4 压到 2。
    """
    h, w = mask.shape
    cur_mid = cur.position
    if abs((h - cur_mid) - book_gap) <= RESCUE_DEV_MIN:
        return cur
    if cur.score >= RESCUE_SELF_OK_SCORE:      # 现役自身足够可信，不冒险动它
        return cur

    xs = sorted(v.position for v in verticals)
    # 界行位置可能落在图外（封面/扉页这类没有版框的页，find_vertical_lines
    # 会给出 x<0 的伪界行）。**必须先夹回 [0, w]**：负的 x0 会让
    # `mask[:, x0:x1]` 变成 numpy 的反向切片而得到**空**数组，`x1-x0`
    # 却还是个大正数，护栏看不出来，一路错到 `_shift_blocks` 才炸
    # （vol03/p0001：xs[0]=-74 → x0=-29 → 切出 0 列 → IndexError）。
    x0 = max(0, int(xs[0]) + RESCUE_MARGIN)
    x1 = min(w, int(xs[-1]) - RESCUE_MARGIN)
    if x1 - x0 < 200:
        return cur
    sub = mask[:, x0:x1]
    cx = (x1 - x0) / 2.0
    base = -float(np.median([v.slope for v in verticals]))
    band = max(10, int(h * 0.15))
    lo, hi = h - band, h - 1

    # 每档倾角各选一个最优候选，再对这些赢家投票——不能把所有档的候选汇成
    # 一池再投票（那样弱候选靠"在很多档上重复出现"就能刷票胜出）。
    per: list[tuple[float, float, float, float]] = []
    for s in np.linspace(base - RESCUE_SLOPE_SPAN, base + RESCUE_SLOPE_SPAN, RESCUE_SLOPE_N):
        _, curve = sample_line_curve(sub, "h", lo, hi, float(s))
        best = None
        for i in local_maxima(curve, radius=5):
            y = lo + i
            if abs(y - lo) <= 3 or abs(y - hi) <= 3:       # 带边界退化值
                continue
            if RESCUE_DOWN_ONLY and y < cur_mid - 1.0:     # 只许往下，不许往上
                continue
            wd, sc = half_height_score_at(curve, i, alpha, hyst)
            if wd > RESCUE_WMAX:
                continue
            a = int(round(wd / 2)) + 4
            dn = curve[min(len(curve), i + a):min(len(curve), i + a + 12)]
            if len(dn) and float(dn.min()) / max(curve[i], 1e-9) > RESCUE_FLANK_MAX:
                continue
            if best is None or sc > best[2]:
                best = (float(y), float(s), sc, wd, float(curve[i]))
        if best is not None:
            per.append(best)
    if not per:
        return cur

    ref_y = h - book_gap
    votes = Counter(int(round(p[0] / 10)) * 10 for p in per)
    mode_y = votes.most_common(1)[0][0]
    near = [p for p in per if abs(p[0] - mode_y) <= 15]
    pick = max(near or per, key=lambda p: p[2])
    if abs(pick[0] - ref_y) > RESCUE_GUARD_D:             # 护栏：落点越界就改选
        pool = [p for p in per if abs(p[0] - ref_y) <= RESCUE_GUARD_D]
        if not pool:
            return cur                                     # 邻域内无候选，不救
        pick = max(pool, key=lambda p: p[2])

    y, s, sc, wd, proj = pick
    # sub 坐标 → 整页：sample_line_curve 对 axis="h" 用 n_perp=sub.shape[1]，
    # 中心是 sub 自己的中心，不是整页 w/2。这里换算错过一次，整页偏 130~145px。
    pos_full = y + s * ((w / 2.0 - x0) - cx)
    return LineMatch(position=pos_full, slope=s, score=sc, width=wd, proj=proj)
