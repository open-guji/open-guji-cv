"""列图投影、去噪、找文字带（2026-10-30 切分模块化第 3 步，从 `utils/column_projection` 原样拆出）。

`denoise_column` 去孤立小连通体，`stamp_noise_density` 量噪点密度，`column_profile`／`column_row_profile`
是矫正后列图的横向／纵向墨投影，`column_text_band` 找文字所在的横向带。都只吃一张列图，与书无关。
"""

from __future__ import annotations

import cv2
import numpy as np


def denoise_column(warped_gray: np.ndarray, ink_threshold: int = 128,
                    min_blob_area: int = 6) -> np.ndarray:
    """清掉矫正后列图里的孤立小连通体噪点（书斑/墨渍/扫描灰尘）。

    只处理二值化后面积 < `min_blob_area` 的连通体——笔画的连通体面积
    通常远大于这个量级，真正的噪点是几像素大小的孤立小点。噪点区域抹成
    背景色（白），其余像素原样保留（不是整体去噪滤波，只删孤立小块）。
    """
    mask = (warped_gray < ink_threshold).astype(np.uint8)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = warped_gray.copy()
    for i in range(1, n_labels):
        if stats[i, cv2.CC_STAT_AREA] < min_blob_area:
            out[labels == i] = 255
    return out


def stamp_noise_density(raw_gray: np.ndarray, ink_threshold: int = 128,
                         lo_area: int = 3, hi_area: int = 60) -> float:
    """整列（未去噪原图）里「中等面积孤立墨点」占全列像素的比例——
    专门抓**背景印章导致的整列散布噪点**，`side_floor`（只看两侧外 25%）天生
    看不见这种不贴边的污染（见 `column-warp` 金标 `vol02/3` 一页，字缝间到处
    是印章残墨的麻点）。

    面积下限 `lo_area=3` 避开单像素级扫描灰尘（`denoise_column` 已经按
    `min_blob_area=6` 清掉更小的，这里在**未去噪的原图**上量、下限故意比它低，
    连最细小的麻点也计入密度）；上限 `hi_area=60` 排除掉字身笔画本体的连通体
    （单个笔画随便也有上百像素）。

    115 列金标实测（`open-guji-dataset/char-segmentation/column-warp`）：
    clean 组 p95=0.0045、max=0.0060；人判 `mixed` 的印章列（`vol02/3` c9）
    单独一条 0.0201，**3.4 倍间隙、零重叠**——注意这条判据只对「印章」这一种
    机制有效，`column-warp` 里另外 3 条 `mixed`（夹注列 `vol01/146` c8、
    局部弯界行 `vol02/188` c3/c4）在这个量上跟 clean 完全混在一起，
    读它们的值仍然落在 0.0017~0.0028，说明这条判据设计范围本来就只覆盖
    「整列噪点」这一族，不是万能判据（延续 `SIDE_FLOOR_MAX` 那次的教训：
    这类池子做不到单指标覆盖四种机制，只能按机制分别做判据、任一命中就拦）。

    全语料验证（vol01+vol02 已生成产物 76 页 684 列）：门槛取 0.007~0.012
    区间内结果完全一致——只拦下 `vol02/3` 整页 9 列里的 8 列（该页目录页
    大面积印章覆盖，人只标了 c9 但其余列同样脏，命中符合预期），
    没有一列 clean 金标被误伤；门槛低到 0.006 会连带误杀 `vol02/151` c2
    （候选·弯界行、人判 clean），故取 **0.007** 留出安全边际。
    """
    mask = (raw_gray < ink_threshold).astype(np.uint8)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    noise_px = sum(int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n_labels)
                   if lo_area <= stats[i, cv2.CC_STAT_AREA] <= hi_area)
    return float(noise_px / mask.size)


def column_profile(warped_gray: np.ndarray, ink_threshold: int = 128) -> np.ndarray:
    """矫正图**沿竖直方向的投影**：长度 = 图宽，每个 x 上的墨占比（0~1）。

    这是 `char-segmentation/column-warp` 金标的核心量——矫正对了的话，这条
    曲线两端应该是空白（界行已清除），中间是字身墨；矫正歪了的话，界行
    残留会从"又窄又高的尖峰"摊成"又宽又矮的鼓包"（一条直线歪了 δ px 就在
    投影上抹开 δ px），所以曲线的形状本身也是残余倾斜的读数。
    """
    return (warped_gray < ink_threshold).astype(np.float64).mean(axis=0)


#: 行墨 ≥ 此值的行当横贯版框行，不进列投影（见 column_text_band）；剩下的行少于 ROWS_KEEP_MIN 就不剔
FRAME_ROW_COV = 0.6
ROWS_KEEP_MIN = 0.5


#: 贴边档找「内侧孤立竖线」（`bar_after`）用的峰值门槛，比内缩档 `bar_min_peak`
#: 低——贴边档已经先证明了边缘真有一条外框线衰减到谷底，这个前提把「误认成字身」
#: 的风险摘掉了大半，可以比内缩档更敢信一条更淡的窄条。vol02 p81c9/p79c1/p159c1/
#: p181c1/p182c9/p57c4 六个页边列实测：内侧那条真线峰值只有 0.118~0.232，远够不上
#: 0.40（当时是按 p73c1 峰 1.00 的样本标定的，没覆盖这么淡的）；全书按 0.10 扫，
#: 命中的都还是页边列（col 1/9），没有一条落在正文腹地列（2026-09-27）。
BAR_AFTER_MIN_PEAK = 0.10


def column_text_band(warped_gray: np.ndarray, ink_threshold: int = 128,
                      edge_ink_eps: float = 0.01, plateau_tol: float = 0.005,
                      max_rule_frac: float = 0.15, bar_min_peak: float = 0.40,
                      bar_max_width: int = 22, inset_look_frac: float = 0.28,
                      bar_after_min_peak: float = BAR_AFTER_MIN_PEAK,
                      ) -> tuple[int, int]:
    """找矫正图里**文字带的左右边界** `(x_left, x_right)`（半开区间，右端不含）。

    边界外侧就是残余界行。判据：界行是一条贯穿的竖直墨线，在 `column_profile`
    上表现为紧贴边缘、由高到低衰减的一段；界行和字身之间有一道墨量的**谷**。
    从两端各自往里扫，分两档——

    * **贴边档**：边缘那一格墨占比 > `edge_ink_eps` —— 在
      `max_rule_frac * 宽度` 的窗口里找**最低点**，边界取第一个降到
      「最低点 + `plateau_tol`」的位置，也就是界行衰减到谷底的那一格。
    * **内缩档**：边缘那一格是空的，但里面藏着一条**孤立的窄墨条**
      （峰 ≥ `bar_min_peak`、宽 ≤ `bar_max_width`、两侧都归零）—— 那是探进
      带里的界行，边界取它的内侧末端。真实界行是**弯的**而 `VLine` 是直的，
      所以界行常常只在列的一端探进来（vol01/47 那几列尤其明显）。
      这一档用**单独的、更宽的**搜索窗口 `inset_look_frac`（默认 28% 宽度）
      —— 实测那些条落在离边 24~35px，贴边档的 15% 窗口（约 28px）够不着；
      放宽是安全的，因为只有真找到"孤立窄条"才动手。
    * 两档都不满足就收手，一个像素也不啃。

    "扫到窗口最低点"这个写法是拿人裁金标标定出来的
    （`char-segmentation/column-warp`）。**上一版是"先吃墨占比 >= 0.35 的界行
    本体、再吃 >= 阈值的裙边"，两头都会翻车，已撤销**：界行被残余倾斜抹糊时
    （整段墨占比只有 0.10~0.12）够不到 0.35，第一步就判成"这侧没界行"、整条
    留在带里；带内有贯穿全高的淡竖痕时（界行降到 0.01 之后**永远停在 0.01**）
    裙边判据一路吃到上限，切进字身 21px。

    **内缩档不能只看峰值**（负结果）：126 列实测"文字腹地"（两侧各去掉 25%，
    那里绝无界行）的列投影峰值均值 0.377、**最高 0.533**，而实测到的内缩界行
    峰值最低 0.40 —— 完全重叠。分得开的是**形状**：界行是零→窄条→零的
    **孤立**结构，字身峰是宽鼓包的一部分、两侧不归零。所以判据是"孤立且窄"，
    `bar_min_peak` 只当辅助门槛。

    两个主阈值的默认值是在金标上**扫曲线**定的，不是挑的单点：
    `plateau_tol` 取 0.002 时命中 57/64、但会切进字身 23px；取 0.005 时命中
    56/64、**切字 0px**。按"宁可留残墨也不切字"取 0.005。
    """
    prof = column_profile(warped_gray, ink_threshold)
    ink = warped_gray < ink_threshold
    rows = ink.mean(axis=1) < FRAME_ROW_COV
    # 判「孤立窄条」用的投影剔掉横贯的版框行（2026-09-26）：条里压着一截上/下版框时整条投影被垫高
    # 0.02~0.1，界行两侧不再归零，孤立判不出来（vol02 p81c9、p181c1 列端那一条里的竖线）。
    # 只给窄条判据用；贴边档找谷底仍用原投影（换投影会让两百来列的带宽抖 1px，没有收益）
    prof_bar = (ink[rows] if rows.sum() >= ROWS_KEEP_MIN * len(rows) else ink).astype(np.float64).mean(axis=0)
    n = len(prof)
    limit = max(1, min(int(round(max_rule_frac * n)), n // 2))
    wide_n = max(1, min(int(round(inset_look_frac * n)), n // 2))

    def bar_after(order: np.ndarray, start: int) -> int | None:
        """`start` 之后（先要有空白）紧接着的一段墨若是孤立窄条，返回它的内侧末端。"""
        wide = prof_bar[order[:wide_n]]
        k = start
        if k >= len(wide) or wide[k] > edge_ink_eps:
            return None
        while k < len(wide) and wide[k] <= edge_ink_eps:
            k += 1
        a = k
        while k < len(wide) and wide[k] > edge_ink_eps:
            k += 1
        if a >= len(wide) or k >= len(wide):
            return None
        if k - a <= bar_max_width and float(wide[a:k].max()) >= bar_after_min_peak:
            return k
        return None

    def scan(order: np.ndarray) -> int:
        window = prof[order[:limit]]
        if window[0] > edge_ink_eps:                 # 贴边档
            floor = float(window.min())
            b = int(np.argmax(window <= floor + plateau_tol))
            # 贴边的界行之内还有一条孤立窄竖线（页边列的双线：外框贴边、内框探进来，
            # vol02 p73c1 实测 x=189~195、峰 1.00、两侧 0.00）：一并算在带外
            inner = bar_after(order, b)
            return b if inner is None else inner
        # 内缩档：在自己的宽窗口里找**峰值最高的那一段**墨，看它是不是孤立窄条。
        # 不能取"第一段"——去噪之后仍有零星 1~2% 的麻点，一段麻点就把前导空白
        # 截断了（vol01/47 c4 实测踩过：真正的界行条在 x=22~30、峰 0.98，却被
        # x=9 处一个 0.013 的麻点挡住，判成"没有条"）。
        wide = prof_bar[order[:wide_n]]
        best = None
        k = 0
        while k < len(wide):
            if wide[k] <= edge_ink_eps:
                k += 1
                continue
            a = k
            while k < len(wide) and wide[k] > edge_ink_eps:
                k += 1
            peak = float(wide[a:k].max())
            if best is None or peak > best[2]:
                best = (a, k, peak)
        if best is None:
            return 0
        a, b_, peak = best
        if b_ >= len(wide):
            return 0                                  # 条没在窗口里收口，多半是字身
        if b_ - a <= bar_max_width and peak >= bar_min_peak:
            return b_
        return 0                                      # 又宽又矮 = 字身，不是界行

    idx = np.arange(n)
    left = scan(idx)
    right = n - scan(idx[::-1])
    if left >= right:                        # 判据失效，原样返回，绝不返回空带
        return 0, n
    return left, right


def column_row_profile(warped_gray: np.ndarray, band: tuple[int, int] | None = None,
                        ink_threshold: int = 128) -> np.ndarray:
    """矫正图**沿水平方向的投影**：长度 = 图高，每个 y 上的墨占比（0~1）。

    `band` 是 `column_text_band` 给的文字带 —— **必须先把两侧界行排除掉再算**，
    否则界行贯穿整列、每一行都带着 0.03~0.06 的底噪，"归不归零"这个判据就废了。
    默认按整幅算，只在调用方已经把界行抹白之后才应该这么用。
    """
    lo, hi = band if band is not None else (0, warped_gray.shape[1])
    return (warped_gray[:, lo:hi] < ink_threshold).astype(np.float64).mean(axis=1)
