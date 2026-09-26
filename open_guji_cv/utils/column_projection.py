"""Step 2（单列射影变换 + 去噪）—— 见 `.claude/doc/segmentation_v2_pipeline.md`。

给定 Step 1（`border_geometry.detect_borders`）里某一列的左右两条边线
（`VLine`，新坐标系：右上角原点、y 向下），把该列从原图裁出并做射影
变换矫正成竖直矩形，再做基础去噪（书斑/墨渍等孤立小连通体）。

`row_boundaries.py`/`peak_line_search.py` 探索阶段都各自写过一次性的
`cv2.getPerspectiveTransform` + `warpPerspective` 代码，没有沉淀成独立
函数——这个模块把它收拢成一处。

Step2 的职责后来又扩了一项：**清掉矫正图两侧的残余界行**。界行是 Step1
给的左右边线本身的墨迹，`warp_column` 把边线映射到 x=0/x=out_w，界行有
宽度（约 5~10px），于是半条线必然留在矫正图里——实测 14 页 126 列
**没有一列是干净的**（两侧 6px 内墨占比中位 0.65~0.75）。这些残留会污染
Step3 的行投影和 Step4 的连通体归属，得在这一步就清掉。

`column_profile` / `column_text_band` / `strip_column_rules` 三个函数就是
干这个的，也是 `char-segmentation/column-warp` 金标的量法定义所在。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .border_geometry import BorderDetectionResult, HLine, VLine


def column_warp_matrix(page_width: int, left: VLine, right: VLine,
                        top_y: float, bottom_y: float, out_w: int | None = None
                        ) -> tuple[np.ndarray, int, int]:
    """算这一列的射影矩阵和输出尺寸，返回 `(M, out_w, out_h)`。

    `warp_column` 用它，金标那边也用它——**把人标的列图坐标反算回原图坐标**
    需要 `M` 的逆。金标一旦有了原图坐标的锚，上游改边线/窗口之后就能把标注
    重新投影到新列图上，而不是整批作废重标（见
    `scripts/migrate_column_warp_gold.py`）。

    ⚠️ 这个矩阵只对**直线**边线成立。三段折线的页（`vline_segments == 3`）
    `warp_column` 会按折点分带、每带一个矩阵——要反算列图坐标得先按 y 落在
    哪一带找对应的矩阵（带界见 `_strip_bounds`）。`out_w` 可外给，分带时三带
    要共用一个宽度。
    """
    if bottom_y <= top_y:
        raise ValueError(f"bottom_y({bottom_y}) must be > top_y({top_y})")

    def to_old_x(vline: VLine, y_new: float) -> float:
        return (page_width - 1) - vline.x_at(y_new)

    lx_top, rx_top = to_old_x(left, top_y), to_old_x(right, top_y)
    lx_bot, rx_bot = to_old_x(left, bottom_y), to_old_x(right, bottom_y)

    if out_w is None:
        out_w = int(round(max(abs(rx_top - lx_top), abs(rx_bot - lx_bot))))
    out_h = int(round(bottom_y - top_y))
    if out_w <= 0 or out_h <= 0:
        raise ValueError(f"warped column size invalid: {out_w}x{out_h}")

    src = np.array([[lx_top, top_y], [rx_top, top_y],
                     [rx_bot, bottom_y], [lx_bot, bottom_y]], dtype=np.float32)
    dst = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    return cv2.getPerspectiveTransform(src, dst), out_w, out_h


def warp_column(gray: np.ndarray, left: VLine, right: VLine,
                 top_y: float = 0.0, bottom_y: float | None = None) -> np.ndarray:
    """把 `left`/`right` 两条竖直边线之间的列矫正成竖直矩形灰度图。

    `left`/`right` 是新坐标系（右上角原点）下的 `VLine`；`top_y`/`bottom_y`
    也是新坐标系的 y（默认整页高度，通常应由 `column_bounds()` /
    `page_column_windows()` 给出，而不是整页边缘——版框外的页边留白不属于
    这一列）。

    输出矩形的宽度取 `left`/`right` 在 `top_y`/`bottom_y` 两处间距的较大者；
    高度取 `bottom_y - top_y`。输出图沿用标准图像坐标系（左上角原点）——
    矫正之后的列图不再是页面的一部分，没必要维持"右上角原点"这个页面级约定。

    **`out_w` 取较大者会不会把内容压扁？不会**（负结果，已查）：梯形→矩形的
    射影映射把**每一条源图水平线都归一到 `out_w`**，实测梯形量最大的那一列
    逐行缩放 1.0010（顶）→ 1.1269（底），每行映射后都精确落在 0..out_w。
    所以 max/min/mean 只决定输出的整体分辨率、不改变顶底之间的相对形变，
    取 max 保证没有任何一行被下采样。
    """
    h, w = gray.shape[:2]
    if bottom_y is None:
        bottom_y = float(h - 1)
    if left.segments == 1 and right.segments == 1:
        m, out_w, out_h = column_warp_matrix(w, left, right, top_y, bottom_y)
        return cv2.warpPerspective(gray, m, (out_w, out_h),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # 三段折线：一个单应变换表示不了折线，按折点把列切成横带各自射影、竖向拼接。
    # 相邻带共享同一组源角点，拼缝天然对齐；out_w 三带取同一个（最大者），否则
    # 拼不起来。左右两条线的折点 y 差几 px（版框有斜率），取均值当带界——那几
    # px 里把线当直线，误差亚像素。
    strips = _strip_bounds(left, right, top_y, bottom_y)
    mats = [column_warp_matrix(w, left, right, a, b) for a, b in strips]
    out_w = max(m[1] for m in mats)
    parts = []
    for (a, b), (_, _, out_h) in zip(strips, mats):
        m, _, _ = column_warp_matrix(w, left, right, a, b, out_w=out_w)
        parts.append(cv2.warpPerspective(gray, m, (out_w, out_h), flags=cv2.INTER_LINEAR,
                                         borderMode=cv2.BORDER_REPLICATE))
    return np.vstack(parts)


def _strip_bounds(left: VLine, right: VLine, top_y: float, bottom_y: float
                  ) -> list[tuple[float, float]]:
    """按两条边线的折点把 [top_y, bottom_y] 切成横带。"""
    ks = sorted(set((a + b) / 2.0 for a, b in zip(left.knots() or right.knots(),
                                                 right.knots() or left.knots())))
    cuts = [top_y] + [k for k in ks if top_y + 2 < k < bottom_y - 2] + [bottom_y]
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


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


def _column_center_x(left: VLine, right: VLine, y: float) -> float:
    return (left.x_at(y) + right.x_at(y)) / 2.0


def _border_y(border: HLine, left: VLine | None, right: VLine | None) -> float:
    """版框线在这一列中心处的 y；没给列线就退回页面右端锚点 x=0。"""
    if left is None or right is None:
        return float(border.y_at(0.0))
    y = border.y_at(0.0)
    for _ in range(2):
        y = border.y_at(_column_center_x(left, right, y))
    return float(y)


def column_bounds(top: HLine, bottom: HLine,
                   head_raise_inner_y: float | None = None,
                   left: VLine | None = None,
                   right: VLine | None = None) -> tuple[float, float]:
    """给 `warp_column` 算 `top_y`/`bottom_y` 的**标准调用约定**。

    版框是斜的（实测上版框斜率最大 0.032），`HLine` 只是一条线，"这一列的
    上下界在哪"取决于沿这条线的哪个 x 取值——接口里没写死，这个函数把约定
    固化下来：**一律取页面右端锚点 `x=0`**（即 `HLine.y_at_right`），不随列
    位置变化。

    **传了 `left`/`right` 就不再用页面右端锚点**，改成沿版框线取"该列中心处"
    的值——这是上面那个取舍的正解，按原计划只改了这一个函数、`warp_column`
    不动。列线本身也是斜的，所以"列中心 x"依赖 y、y 又依赖 x，迭代两次就
    收敛到亚像素。

    不传 `left`/`right` 时退回原约定（一律取 `x=0`），代价是已知的、如实
    记着：越靠左的列这个锚点离该列真实版框越远——14 页 126 列实测，`y_at(0)`
    与"该列中心处的版框 y"相差 top 均值 14.5px / 最大 54.4px（28 列超 20px），
    而且**方向全部同号**（锚点一律落在真实版框**下方**）。后果两个：列图
    根本不含上版框线，Step 3 想拿版框锚行拿不到；抬头列更是整段被切。

    抬头列传 `head_raise_inner_y`（`BorderDetectionResult.head_raise` 里该列
    的 `inner_y`；同一列有多级台阶时传**最小的那个**，即最高的一级），上界
    直接用它——抬头字顶到主版框以上，用主版框会把抬头字齐腰切掉。抬头框本身
    是局部量、不贯穿全页，没有"沿哪个 x 取值"的问题。
    """
    if head_raise_inner_y is not None:
        return float(head_raise_inner_y), _border_y(bottom, left, right)
    return _border_y(top, left, right), _border_y(bottom, left, right)


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


STAMP_NOISE_MAX = 0.007


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


def column_text_band(warped_gray: np.ndarray, ink_threshold: int = 128,
                      edge_ink_eps: float = 0.01, plateau_tol: float = 0.005,
                      max_rule_frac: float = 0.15, bar_min_peak: float = 0.40,
                      bar_max_width: int = 22, inset_look_frac: float = 0.28
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
        if k - a <= bar_max_width and float(wide[a:k].max()) >= bar_min_peak:
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


def strip_column_rules(warped_gray: np.ndarray, ink_threshold: int = 128,
                        slab_rows: int | None = 240, **kwargs) -> np.ndarray:
    """把矫正图两侧的残余界行抹成背景白，返回**同尺寸**的新图。

    **分横条做，不是整列一个带**（`slab_rows` 给条高，`None` 退回整列一个带）。
    真实界行是**弯的**、`VLine` 是直的，所以界行常常只在列的某一段探进带里——
    整列平均之后那一段被稀释、看不见，抹白就漏掉它。实测 vol01/47 有 5 处
    界行只在列的一端探进来 10~23px，整列口径一处都清不掉，按 240 行分条之后
    全部清掉。

    抹白而不是裁掉——矫正图的局部坐标系是 Step3(`row-boundaries` 金标)、
    Step4 共用的锚，裁一刀所有挂在上面的坐标就全漂了。要裁的调用方自己
    按 `column_text_band` 的返回值裁。
    """
    out = warped_gray.copy()
    h = warped_gray.shape[0]
    if slab_rows is None or h <= slab_rows:
        bounds = [(0, h)]
    else:
        n = max(1, round(h / slab_rows))
        bounds = [(int(i * h / n), int((i + 1) * h / n)) for i in range(n)]
    for lo, hi in bounds:
        left, right = column_text_band(warped_gray[lo:hi], ink_threshold, **kwargs)
        out[lo:hi, :left] = 255
        out[lo:hi, right:] = 255
    return out


def column_row_profile(warped_gray: np.ndarray, band: tuple[int, int] | None = None,
                        ink_threshold: int = 128) -> np.ndarray:
    """矫正图**沿水平方向的投影**：长度 = 图高，每个 y 上的墨占比（0~1）。

    `band` 是 `column_text_band` 给的文字带 —— **必须先把两侧界行排除掉再算**，
    否则界行贯穿整列、每一行都带着 0.03~0.06 的底噪，"归不归零"这个判据就废了。
    默认按整幅算，只在调用方已经把界行抹白之后才应该这么用。
    """
    lo, hi = band if band is not None else (0, warped_gray.shape[1])
    return (warped_gray[:, lo:hi] < ink_threshold).astype(np.float64).mean(axis=1)


#: e 档（薄框接低平底）的三个尺子，bxgb 54 页 1026 列 column_raw 上标定（2026-09-17）：
#: - `FLOOR_T` 低平底上限。b 档误判的根源是框后面那段 0.03~0.14 的底噪（界行残迹、
#:   纸纹）超过 `ink_eps`=0.02，把框和整个字身连成一段（71~372 行）；0.25 把它
#:   收进「底」里，而字身行墨中位 0.598，不会被当成底。
#: - `FLOOR_RUN` 低平底至少持续几行。版框与首字之间是天头（`top_slack` ≈ 35px），
#:   字的横笔下方几行内必接其余笔画：上端 b 档 109 列里 floor ≥6 的占 94%、a 档
#:   （已正确切掉的 900 列）99%——同一把尺子在 a 档上给出的切点与现行削行 |d|≤2。
#: - `FLUSH_MAX` 「贴边」的定义。非抬头列的矫正图第 0 行**就是 Step1 拟合的版框线**
#:   （`page_column_windows`：top_y = btop，BODY_PAD=0），贴边的高墨薄段只能是框，
#:   首字离它还有整个天头——所以上端贴边时不需要边距证据。
FLOOR_T = 0.25
FLOOR_RUN = 6
FLUSH_MAX = 3
#: 贴边端的低平底只需这么几行。贴边时框的身份由位置定死（第 0 行就是 Step1 的版框
#: 线），低平底只是用来找**框的下沿**，不必再当「天头」证据；首字离框近（天头 < 6 行）
#: 的列用 6 行会漏：bxgb 1026 个贴边上端里 6 列（p4c3「聞」等）漏抹，改 2 行后 0 列，
#: vol01 1669 个贴边上端零变化。非贴边（下端/抬头列）仍用 FLOOR_RUN + 边距证据。
FLOOR_RUN_FLUSH = 2
#: 非贴边（下端的框被 BOTTOM_PAD 内缩 ~40 行；抬头列的框被 HEAD_PAD 内缩）时要
#: **边距证据**：版框横贯整列宽，文字带外的边距里也是墨；字的横笔止于文字带，
#: 边距里只有界行底噪。实测框行边距墨中位 1.000（p5 0.75），首字行 0.333（p95 0.667）；
#: 阈值 0.7：框行 96.5% 过、首字行 4.9% 过。边距合计不足 `MARGIN_MIN_PX` 时没有证据，
#: 不判 e、退回原有 b/c——宁可留框渣，绝不切「一/二/三」。
MARGIN_T = 0.7
MARGIN_MIN_PX = 6
#: 双线版框（2026-09-26）：册配置 `frame_layers` 声明某端有两层时，剥掉第一道线之后**继续往里
#: 找第二道**。vol02 实测只剥一道：列尾 499/1674 列留着紧贴末字的那道细虚线（内框），列首 352 列
#: 留着第二道——Step4 再把它收进字的图块（列尾约四成的图块底下挂一截虚线），或当成一个「字」。
#: 第二道的判据：离第一道 ≤ `outer_gap`（册配置）× LAYER2_GAP_K + LAYER2_GAP_ADD 行，
#: 本身薄（≤ LAYER2_MAX_ROWS 行），且**横向跨度**（这几行里最左墨到最右墨）≥ LAYER2_EXTENT
#: × 文字带宽——虚线断断续续、墨占比不高，但从头贯到尾；「一」「二」「三」「王」的横
#: 只占文字带六七成，够不上。拿不准就不剥（与 b 档同一纪律）。
LAYER2_GAP_K = 1.5
LAYER2_GAP_ADD = 12
LAYER2_MAX_ROWS = 30     # 外框粗线实测 18~24 行（与 border_max_rows 同一把尺）
LAYER2_EXTENT = 0.85
LAYER2_MARGIN_RISE = 0.3   # 边距证据：这几行的边距墨比全列边距中位高出这么多（界行本底不算）
#: 第二道的**下沿**不按「墨归零」找（2026-09-26）：内框紧贴末字时，线与字之间常只隔几行
#: 0.03~0.1 的淡墨（字的收笔、麻点），按 > ink_eps 连成一段就把字身也算进来，厚度超 30 行判不是线
#: ——vol02 残线 126 列里约九成是这样漏的。改为从这段的起点往里走，过了峰值之后行墨跌破
#: LAYER2_FLOOR 或跌到峰值 × LAYER2_HALF 以下，再带上一路下降的至多 LAYER2_FADE 行淡边，就是线的
#: 下沿；再往里是字，不动（先试过「谷底」判据：字底 0.15~0.25 的收笔尾巴会被当成线的一部分削掉十来行）。
LAYER2_FLOOR = 0.15
LAYER2_HALF = 0.5
LAYER2_FADE = 3
#: 线要**尖**：峰值一半以上的行不超过 LAYER2_CORE_MAX 行（内框虚线实测 3~10 行）；只有峰值
#: ≥ LAYER2_BOLD 的粗外框（18~24 行、满宽实墨）才放宽到 LAYER2_MAX_ROWS。字的底部是
#: 0.2~0.45 的宽鼓包、几十行高——不加这条，剥第三道时会把末字下半当成线（vol02 p187c6 实测）。
LAYER2_CORE_MAX = 12
LAYER2_BOLD = 0.8
#: 线要**陡起**：峰值一半之前紧挨着的、行墨 > LAYER2_RAMP_INK 的连续行不超过 LAYER2_RAMP 行。
#: 线是白纸上直接冒出来的（实测 0~3 行），字底是十来行 0.1~0.2 的淡墨慢慢爬上来（p102c1、p31c7）。
#: 粗外框（峰 ≥ LAYER2_BOLD）不管：略斜的粗线投影也是缓起的（p22c9 十行爬到 0.99）
LAYER2_RAMP = 5
LAYER2_RAMP_INK = 0.05
#: 与上一刀之间至少要有这么多行白（≤ ink_eps）：两道框之间隔着纸，一段不断的淡墨后面冒出的「线」是字底
#: （p18c8 实测：第二道之后 17 行 0.05~0.1 的淡墨，接着一段 0.4 的横墨被当成第三道）。两道框可以挨得
#: 很近（p17c4 只隔 2 行、p17c1 隔 1 行），所以只要 1 行；粗线（峰 ≥ LAYER2_BOLD，p178c9 两道粗线只隔一行 0.1）
#: 或上一刀切在粗线身里（切口处行墨 ≥ LAYER2_BOLD，p23c8）不要求
LAYER2_BLANK_MIN = 1
#: **Step1 位置证据**（只用于下端）：Step1 的下版框线多半落在内框上（`border_bottom_in_column`）。
#: 候选线离它 ≤ INNER_SEARCH 行时，跨度只要 ≥ LAYER2_EXTENT_HINT 就认——磨损的内框虚线常只剩
#: 三成到七成宽（vol02 列尾残线 126 列里 87 列靠这一条才认出来）。末格的「一」离版框约半格，落不进
#: 这个窗口；贴着内框的字底另有上面的尖/陡起/隔白三条挡着。Step1 线落在外框上的列（约一成）
#: 这条证据用不上，内框靠跨度或边距证据认。
LAYER2_EXTENT_HINT = 0.35
#: 下端还有一刀：**Step1 的下版框就是内框线**（vol02 实测残线正落在 `border_bottom_in_column` ±8 行），
#: 而字不会越过内框。剥完外面几道之后，若内框线还在（紧贴末字、与字粘连，按行分不出段的那种，
#: vol02 约 200 列），就在 Step1 给的位置 ±INNER_SEARCH 行里找覆盖最高的一行（≥ INNER_COV），
#: 连同它上沿 ≥ INNER_EDGE 的几行一起、往下全抹。只在册配置声明下端有两层时做。
INNER_SEARCH = 10
INNER_COV = 0.35
INNER_EDGE = 0.15


def _thin_bar_then_floor(p: np.ndarray, blank: int, bar_coverage: float,
                         floor_t: float, floor_run: int, cap: int = 40
                         ) -> tuple[int, int] | None:
    """从 `blank` 起在 `cap` 行内找「高墨薄段（≥bar_coverage）→ 低平底（≤floor_t，
    连续 ≥floor_run 行）」；找到返回 `(bar_start, bar_end)`，`bar_end` 是第一行低平底
    的下标（切到这里正好把框的下沿含进去）。框的下沿常有一两行 0.3~0.5 的过渡，
    过渡行既不算框也不算底，跳过继续看。"""
    n = len(p)
    seen = False
    start: int | None = None
    for j in range(blank, min(n, blank + cap)):
        v = float(p[j])
        if v >= bar_coverage:
            if start is None:
                start = j
            seen = True
        elif seen and v < floor_t:
            k = j
            while k < n and k < j + floor_run and p[k] <= floor_t:
                k += 1
            if k - j >= floor_run and start is not None:
                return start, j
            return None
    return None


def column_border_trim(warped_gray: np.ndarray, band: tuple[int, int] | None = None,
                        ink_threshold: int = 128, ink_eps: float = 0.02,
                        border_max_rows: int = 30, inset_look: int = 70,
                        glue_px: int = 3, bar_probe: int = 8,
                        bar_coverage: float = 0.65, inset_min_peak: float = 0.15,
                        margin_profile: np.ndarray | None = None,
                        floor_t: float = FLOOR_T, floor_run: int = FLOOR_RUN,
                        flush_max: int = FLUSH_MAX, margin_t: float = MARGIN_T,
                        layers: tuple[int, int] = (1, 1),
                        layer_gap: tuple[float | None, float | None] = (None, None),
                        layer_hint: tuple[float | None, float | None] = (None, None),
                        ) -> tuple[tuple[int, str], tuple[int, str]]:
    """上下版框残墨该削掉几行 —— 返回 `((top_px, top_case), (bottom_px, bottom_case))`。

    **e 档（2026-09-17 加，bxgb 列端残框 89 列的病根）**：边缘一段薄高墨、之后是一段
    **持续的低平底**、再往里才是首字——这是「版框 → 天头 → 首字」的形态，框应当整段
    削掉。此前它落进 b 档只削 `glue_px`=3 行，框剩 3~7 行留在列图里，Step4 再把它
    带进首字的图块（人裁看到的「含有边框噪点」）。原因是天头那段有 0.03~0.14 的
    界行/纸纹底噪，超过 `ink_eps`，于是 `run` 一路走到字身、`thick` 71~372 行，被
    当成「框粘着字」。判 e 要两条：`_thin_bar_then_floor` 找到形态，且 **贴边**
    （`blank <= flush_max`，见 FLUSH_MAX 注）或 **边距里也是墨**（`margin_profile`，
    见 MARGIN_T 注）二者之一。只在 `thick > border_max_rows` 这一支里判——a/d 档
    的行为一位不动。`margin_profile` 由 `clean_column` 在 **抹界行之前** 的图上算，
    别的调用方不传就只认贴边这一条。

    上下界用的是 `column_bounds` 的口径（页面右端 x=0 锚点），落点未必正好压在
    版框上，所以矫正图的头尾常常带进一截版框线。判据在水平投影上分四档：

    * **a 档**：边缘就有墨，且**迅速归零**（连续墨行 <= `border_max_rows`）——
      那一段就是版框本体，整段削掉。
    * **b 档**：边缘有墨且**不归零**（连续墨行很长）——版框跟首字粘连，分不出
      界在哪，只削 `glue_px`（默认 3）行，宁可留一点也不切字。
    * **c 档**：边缘那一片是空白，往里第一段墨又厚又是字——这一端没带进版框，
      **不动**。
    * **d 档**：边缘先是一段空白，往里才碰到一条**薄横线**——版框"内缩"了，
      把空白连同横线一起削掉。这是 `column_bounds` 取 x=0 锚点的直接后果：
      锚点越过了该列真实版框，版框线就落在图里面而不是边上。32 列金标里
      **下端有 8 条是这种**（空白 5~47 行），锚点偏移量 10~49px，只按"边缘
      有没有墨"判会全部漏掉。

    分 a/b/c/d 靠两把尺子，都是拿 32 列金标标定的：

    1. **厚度**（`border_max_rows`）分"版框线"和"字"：跳过前导空白之后第一段
       连续墨的厚度实测**要么 3~13 行（版框线）、要么 91~121 行（首字，跟
       `row-boundaries` 金标的字格高 108.8px 对得上）**，中间 13→91 完全没有
       样本，阈值取 30 落在空档里、且离两边都有余量。
    2. **起始陡度**（`bar_coverage` / `bar_probe`）分"厚墨段是纯首字"还是
       "版框粘着首字"：版框粘着字时墨占比在头 3~4 行就冲到 0.74~0.93，纯首字
       的头 8 行最高只到 0.50。

    **行墨占比本身不能当判据**（负结果，试过了）：正文中段的字身行墨占比最高
    能到 0.747、中位 0.598，跟内缩版框横线的 0.56~0.93 **完全重叠**——带长
    横画的字（一/三/王之类）整行就是满的。只有把探测限制在"某段墨的头几行"
    才分得开，因为字的顶边必然是细的。
    """
    prof = column_row_profile(warped_gray, band, ink_threshold)
    lo_, hi_ = band if band is not None else (0, warped_gray.shape[1])
    bink = warped_gray[:, lo_:hi_] < ink_threshold
    bw = max(1, hi_ - lo_)

    def line_end(p: np.ndarray, j: int) -> int | None:
        """从线段起点 `j` 往里找线的下沿（LAYER2_FLOOR / LAYER2_HALF 注）；厚过 LAYER2_MAX_ROWS 返回 None。"""
        n = len(p)
        pk = 0.0
        i = j
        while i < n:
            if i - j > LAYER2_MAX_ROWS:
                return None
            pk = max(pk, float(p[i]))
            if pk >= inset_min_peak and (p[i] < LAYER2_FLOOR or p[i] < LAYER2_HALF * pk):
                # 线的淡边（**严格**一路往下走的至多 LAYER2_FADE 行）一起剥掉，别留一两行渣；持平或回升就是字了
                e = i
                while e < min(n, i + LAYER2_FADE) and p[e] > ink_eps and (e == i or p[e] < p[e - 1]):
                    e += 1
                return e
            i += 1
        return i

    def second_layer(p: np.ndarray, ink2: np.ndarray, cut: int, gap: float | None,
                     m: np.ndarray | None = None, hint: float | None = None,
                     glued: bool = False) -> int | None:
        """`cut` 之后找第二道框线（见 LAYER2_* 注）；找到返回它的下沿，否则 None。

        `hint`：Step1 内框线离这一端的行数（位置证据，见 LAYER2_EXTENT_HINT 注）。
        `glued`：认不认与字粘着的线（只给下端：列首第二道之后紧跟首字的顶横，
        分不清是线还是字——vol02 p101c6、p35c4 试过，削掉的是首字的顶，列首照旧要求线后归零）。"""
        if gap is None:
            return None
        j = cut
        limit = cut + int(gap * LAYER2_GAP_K + LAYER2_GAP_ADD)
        # 上一刀留下的淡尾（行墨仍在**严格**往下掉，p11c1：e 档切在 0.64→0.21→0.16 的半截上）算上一道的，跳过
        while 0 < j < len(p) and p[j] > ink_eps and p[j] < p[j - 1]:
            j += 1
        tail = j
        while True:
            while j < len(p) and j < limit and p[j] <= ink_eps:
                j += 1
            if j >= len(p) or j >= limit:
                return None
            k = j
            while k < len(p) and p[k] > ink_eps:
                k += 1
            if float(p[j:k].max()) >= inset_min_peak:
                break
            j = k                                # 噪点段（vol02 p123c9：两道框之间 3 行麻点）：跳过接着找
        if glued:
            k = line_end(p, j)
        else:                                    # 老口径：线之后必须归零，下沿就是归零处
            k = j
            while k < len(p) and p[k] > ink_eps:
                k += 1
            k = None if k - j > LAYER2_MAX_ROWS else k
        if k is None:
            return None
        pk = float(p[j:k].max())
        if int((p[tail:j] <= ink_eps).sum()) < LAYER2_BLANK_MIN and pk < LAYER2_BOLD \
                and not (cut < len(p) and p[cut] >= LAYER2_BOLD):
            return None                          # 两道框之间必隔着白纸；紧接上一道的淡墨是字的底
        core = int((p[j:k] >= 0.5 * pk).sum())
        if core > LAYER2_CORE_MAX and pk < LAYER2_BOLD:
            return None
        c0 = j + int(np.argmax(p[j:k] >= 0.5 * pk))
        r = c0
        while r - 1 >= j and p[r - 1] > LAYER2_RAMP_INK:
            r -= 1
        if c0 - r > LAYER2_RAMP and pk < LAYER2_BOLD:
            return None                          # 缓起：字的底边，不是线
        cols = np.where(ink2[j:k].any(axis=0))[0]
        extent = (cols[-1] - cols[0] + 1) / bw if len(cols) else 0.0
        if extent >= LAYER2_EXTENT:
            return k
        if hint is not None and j - INNER_SEARCH <= hint <= k + INNER_SEARCH \
                and extent >= LAYER2_EXTENT_HINT:
            return k
        # 跨度不够（磨损的框线只剩几截，vol02 实测列首第二道常只有 0.5~0.8 宽）时看**边距证据**：
        # 框线横贯整列、在文字带外的边距里也是墨；字止于文字带（口径同 e 档的 MARGIN_T）
        # 边距里常年有界行（每一行都是墨），所以比的是**高出这一列边距的常态**多少，不是绝对值
        if m is not None and float(m[j:k].max()) >= margin_t and \
                float(m[j:k].max()) - float(np.median(m)) >= LAYER2_MARGIN_RISE:
            return k
        return None

    def two(p: np.ndarray, m: np.ndarray | None, ink2: np.ndarray, n_layers: int,
            gap: float | None, hint: float | None = None, glued: bool = False) -> tuple[int, str]:
        px, case = one(p, m)
        if n_layers >= 2 and case in ("a", "d", "e") and px:
            # 至多再剥两道：vol02 有的列尾除了内外两道框，最外还压着一截页边/上一道框的残墨
            # （第一刀削掉的是那截，外框粗线与内框虚线都还在，p17c4 实测）
            got = 0
            for _ in range(2):
                k = second_layer(p, ink2, px, gap, m, hint, glued)
                if k is None:
                    break
                px, got = k, got + 1
            if got:
                return px, case + str(got + 1)
        return px, case

    def one(p: np.ndarray, m: np.ndarray | None) -> tuple[int, str]:
        # 从边缘往里找「第一段够格的墨」。噪点段要**跳过去接着找**，不能
        # 见到一段弱墨就收工（2026-09-18 修）——原先判成噪点直接 `return c`，
        # 于是扫描停在噪点上，再也看不到它后面的真框：
        # bxgb p16c17 下端实测，外缘 7 行白 → 7 行弱墨（峰值 0.062）→ 22 行白
        # → **真框（峰值 1.000）**，判了 c「这一端没带进版框」，框墨整条留在
        # 列图里。全书 53 个 c 档端口里 46 个是这么漏的（峰值 0.93~1.00）。
        #
        # 连带影响：`column_gate` 量墨跨度推 `n_raised_hint` 时把这条框墨算成
        # 字，跨度多出 0.5~0.7 格 → 误判「这列多一个字」→ DP 多切一格。
        start = 0
        blank = run = 0
        while True:
            blank = start
            while blank < len(p) and p[blank] <= ink_eps:
                blank += 1
            if blank > inset_look or blank >= len(p):
                return 0, "c"                 # 边缘一大片空白，里面是正文
            run = blank
            while run < len(p) and p[run] > ink_eps:
                run += 1
            thick = run - blank
            if thick > border_max_rows:
                break                          # 厚墨段：交给下面的 e/b/c 判据
            if blank == 0:
                return run, "a"                 # 贴着边缘，削掉几行无害
            # 内缩档：要求这条线本身有像样的墨，否则那是噪点不是版框
            # （vol01/142 c6 上端：空白 30 行后 3 行、墨占比只有 0.03，
            #   人裁的结论是"没残墨"，早先按 d 档削了 33 行是假阳性）
            if float(p[blank:run].max()) >= inset_min_peak:
                return run, "d"
            start = run                        # 是噪点——跳过它继续往里找
        # e 档：run 很长只是因为天头底噪 > ink_eps。头部若是「薄高墨段 → 持续低平底」，
        # 那就是框接天头，不是框粘着字（理由与实测见函数 docstring 及 FLOOR_T 注）。
        flush = blank <= flush_max
        e = _thin_bar_then_floor(p, blank, bar_coverage, floor_t,
                                 min(floor_run, FLOOR_RUN_FLUSH) if flush else floor_run)
        if e is not None:
            bar_start, bar_end = e
            margin_ok = (m is not None and bar_end > bar_start
                         and float(np.median(m[bar_start:bar_end])) >= margin_t)
            if flush or margin_ok:
                return bar_end, "e"
        # 厚墨段：是版框粘着字，还是**压根就是字**？看起始陡度——版框线一上来
        # 就满宽（头 3~4 行冲到 0.74~0.93），字的顶/底边必然是细的、缓起。
        # 这一条以前只在内缩档用，贴边档一律判 b（粘连），结果把"末字顶到
        # 边缘"整批误报成版框：64 条端裁决实测错 7 条，全是底端的 b→金标 none。
        if float(p[blank:blank + bar_probe].max()) >= bar_coverage:
            return blank + glue_px, "b"        # 版框粘着字，只削一点
        return 0, "c"                           # 是字不是版框，什么都不削

    mrev = None if margin_profile is None else margin_profile[::-1]
    return (two(prof, margin_profile, bink, layers[0], layer_gap[0], layer_hint[0]),
            two(prof[::-1], mrev, bink[::-1], layers[1], layer_gap[1], layer_hint[1], glued=True))


def strip_column_borders(warped_gray: np.ndarray, band: tuple[int, int] | None = None,
                          **kwargs) -> np.ndarray:
    """把上下版框残墨抹成背景白，返回**同尺寸**的新图（理由同 `strip_column_rules`）。

    调用顺序是**先侧后上下**：`strip_column_rules` -> `column_text_band` ->
    这个函数，因为"归不归零"必须在排除了两侧界行的水平投影上判。
    """
    (top_px, _), (bot_px, _) = column_border_trim(warped_gray, band, **kwargs)
    out = warped_gray.copy()
    if top_px:
        out[:top_px] = 255
    if bot_px:
        out[warped_gray.shape[0] - bot_px:] = 255
    return out


def clean_column(warped_gray: np.ndarray, ink_threshold: int = 128,
                  **kwargs) -> tuple[np.ndarray, dict]:
    """Step2 的收尾：去噪 + 清两侧界行 + 清上下版框，返回 `(清干净的图, 诊断)`。

    **顺序是有讲究的，这个函数存在的意义就是把它固化下来**：

    1. `column_text_band` 在**原始矫正图**上定文字带 —— 这一步必须在抹白之前
       做，抹白之后边缘变成纯白，`column_text_band` 会判成"这侧没界行"而返回
       整幅宽度；
    2. `strip_column_rules` 抹掉带外的界行；
    3. `column_border_trim` 在**抹白之后的图上、且只在文字带宽度内**算水平
       投影 —— 两侧界行贯穿整列，不排除掉的话每一行都带着底噪，"归不归零"
       这个判据就废了；带外那片白也要排除，否则整条曲线被稀释约 9%，
       `ink_eps` 这类阈值全部失准。

    诊断字典里带 `band` / `top`/`bottom` 的削除行数与档位，方便评测和标注页复用。
    """
    denoised = denoise_column(warped_gray, ink_threshold=ink_threshold)
    band = column_text_band(denoised, ink_threshold=ink_threshold)
    no_rules = strip_column_rules(denoised, ink_threshold=ink_threshold)
    # e 档的边距证据必须在**抹界行之前**的图上算——抹白之后带外全是白，
    # 版框横贯整列这一特征就看不见了（见 column_border_trim 的 MARGIN_T 注）。
    margin_profile = None
    lo, hi = band
    if lo + (denoised.shape[1] - hi) >= MARGIN_MIN_PX:
        binm = denoised < ink_threshold
        margin_profile = np.concatenate([binm[:, :lo], binm[:, hi:]], axis=1).mean(axis=1)
    inner_bottom = kwargs.pop("inner_bottom", None)
    hint = (None, None if inner_bottom is None else denoised.shape[0] - inner_bottom)
    (top_px, top_case), (bot_px, bot_case) = column_border_trim(
        no_rules, band, ink_threshold=ink_threshold, margin_profile=margin_profile,
        layer_hint=hint, **kwargs)
    layers = kwargs.get("layers", (1, 1))
    if inner_bottom is not None and layers[1] >= 2:
        prof = column_row_profile(no_rules, band, ink_threshold)
        h = len(prof)
        y0 = max(0, int(round(inner_bottom)) - INNER_SEARCH)
        y1 = min(h, int(round(inner_bottom)) + INNER_SEARCH + 1)
        if y1 > y0:
            r = y0 + int(np.argmax(prof[y0:y1]))
            if prof[r] >= INNER_COV:
                t = r
                while t - 1 >= y0 - 4 and prof[t - 1] >= INNER_EDGE:
                    t -= 1
                if h - t > bot_px:
                    bot_px, bot_case = h - t, bot_case + "i"
    out = no_rules.copy()
    if top_px:
        out[:top_px] = 255
    if bot_px:
        out[out.shape[0] - bot_px:] = 255
    return out, {"band": band,
                  "top": {"px": top_px, "case": top_case},
                  "bottom": {"px": bot_px, "case": bot_case}}


# ── 逐列的矫正窗口 ───────────────────────────────────────────

BODY_PAD = 0.0     # 普通列在版框之外额外留的余量（上界；下界见 BOTTOM_PAD）

BOTTOM_PAD = 40.0
# 抬头列上界在抬头框**内边框线心**之上再开的余量（2026-09-08 用户实审 vol01/32
# c5「太祖」：窗口顶边 = inner_y = 307 正压在「太」的顶横上，列图第 3 行就有墨，
# 抬头字顶被切）。线心本来就带半条线宽，字又常顶着线写；开 20px 让字完整进来，
# 多进来的框线由 Step 3 的 top_slack 与 Step 4 的框线闸处理。20px 时「太」的竖笔尖仍顶边，取 30。
HEAD_PAD = 30.0
# **下界要多开一截**（2026-09-03 加）。`detect_borders` 的下版框线系统性偏上，
# 窗口就切在末字中部：dev_set 155 列实测，下界到真实版框线之间还剩字墨
# **中位 21px、最大 69px，83% 的列被切掉 >5px**（目视复核 vol01/60c4、
# vol02/181c5、vol01/137c6、vol01/24c1，红线切断「托」「更」「著」「淵」下半）。
# 偏差呈双峰：45% 的列 ≤0（定位准），38% >15px，长尾整页出现
# （01/60、02/3、02/181、01/137 多列同时偏），是下版框定位问题不是随机噪声。
#
# ⚠️ **别用连通体高度差量这个偏差**——笔画被切断后就不再与列图内的部分相连，
# 那样只能量到 2px，低估整整一个量级。要量「下界到版框线上沿之间还有多少字墨」。
#
# 多开进来的版框线不用担心：`clean_column` 的 `column_border_trim` 本来就负责
# 抹掉上下版框，它在文字带宽度内按水平投影归零判边，版框线进到列图里正是它
# 设计要处理的输入。40px 覆盖实测最大切幅 69px 里的绝大多数，又不至于把下一
# 页/页边噪声卷进来。见 doc/step3_error_survey.md 戊类、
# 反馈批次 2026-09-03-step1-bottom-clip。


@dataclass
class ColumnWindow:
    """一列该从哪儿矫正到哪儿——`warp_column` 的参数由这里算，不要再由调用方
    传页级标量。

    以前的做法是整页共用一个 `top_y = top.y_at(0)`（版框在**页面右端**处的
    y）。版框是斜的，越靠左的列这个锚点离该列真实版框越远——14 页 126 列
    实测均值 14.5px、最大 54.4px，而且**一律偏下**，等于列图顶端切进了正文，
    首字被削掉一截（`open-guji-dataset/char-segmentation/column-warp` 的
    known_limitations 记过这个现象）。抬头列更狠：列图裁在主版框上，而抬头
    字整段在版框以上，实测被切掉 140~187px，抬头字直接没了。
    """

    col: int                       # 列号，从右到左、从 1 开始
    left: VLine
    right: VLine
    top_y: float                   # 矫正窗口上界（新坐标 y）
    bottom_y: float                # 矫正窗口下界
    border_top_y: float            # **主**上版框在该列的 y（新坐标）
    border_bottom_y: float
    raised: bool                   # 这一列是不是抬头列
    head_raise_inner_y: float | None = None

    @property
    def border_top_in_column(self) -> float:
        """主上版框在**列图坐标**里的 y——Step 3 的 `border_top` 要这个值。
        普通列是 0；抬头列是正数（列图顶端在版框之上）。"""
        return self.border_top_y - self.top_y

    @property
    def border_bottom_in_column(self) -> float:
        return self.border_bottom_y - self.top_y


def page_column_windows(result: BorderDetectionResult,
                         body_pad: float = BODY_PAD,
                         bottom_pad: float = BOTTOM_PAD,
                         head_pad: float = HEAD_PAD) -> list[ColumnWindow]:
    """整页每一列的矫正窗口——上下界**逐列**算（委派给 `column_bounds`），
    抬头列自动用抬头框的内边框当上界。

    `result` 直接用 `border_geometry.detect_borders()` 的输出：`head_raise`
    已经由 `detect_head_raise()` 填好，调用方不需要再给抬头先验。同一列若有
    多级台阶，取 `inner_y` **最小**的那个（最高的一级）。

    `bottom_pad` 与 `body_pad` **分开**：下版框探测系统性偏上，下界要多开一截
    才不会切掉末字下半，多进来的版框线由 `clean_column` 抹掉。理由与实测见
    `BOTTOM_PAD`。
    """
    hr: dict[int, float] = {}
    for b in result.head_raise:
        hr[b.col] = min(hr.get(b.col, b.inner_y), b.inner_y)
    out: list[ColumnWindow] = []
    for i in range(len(result.verticals) - 1):
        col = i + 1
        right_v, left_v = result.verticals[i], result.verticals[i + 1]
        btop, bbot = column_bounds(result.top, result.bottom,
                                    left=left_v, right=right_v)
        raised_top = hr.get(col)
        top_y, bottom_y = column_bounds(
            result.top, result.bottom, head_raise_inner_y=raised_top,
            left=left_v, right=right_v)
        top_y -= body_pad
        if raised_top is not None:
            top_y -= head_pad                  # 见 HEAD_PAD
        bottom_y += bottom_pad
        top_y = max(0.0, min(top_y, btop))
        bottom_y = min(float(result.height - 1), max(bottom_y, bbot))
        out.append(ColumnWindow(
            col=col, left=left_v, right=right_v,
            top_y=float(top_y), bottom_y=float(bottom_y),
            border_top_y=float(btop), border_bottom_y=float(bbot),
            raised=raised_top is not None,
            head_raise_inner_y=None if raised_top is None else float(raised_top)))
    return out


#: `refine_top_by_frame`（2026-09-20）：列窗上界之上再看这么多行找版框。
TOP_REFINE_PROBE = 90
#: 认框用满宽段——行墨占比 ≥ 此值且连续 ≥ TOP_REFINE_MIN_RUN 行。与 Step2 `frame_residue` /
#: Step4 `FRAME_BAND_COV` 同一把尺（bxgb 1065 个削干净端口零误报；二/三 的横笔 ≤0.7 够不着）。
TOP_REFINE_COV = 0.85
TOP_REFINE_MIN_RUN = 3
#: 框下沿离 top_y 至少这么多行才动（≤2 行是正常的贴框，别为几像素折腾）。
TOP_REFINE_MIN_GAP = 3
#: 探针要越过 top_y 往下再看这么多行（2026-09-19）。**不看下面就会认错框**：
#: Step1 把 top_y 正正切在真框上时，真框被探针窗口的下边界腰斩、凑不满 MIN_RUN，
#: 于是函数转而抓住更上面那条**外框/上欄線**，把 top_y 提到它下沿——真框反被圈进列图。
#: vol02 实测被上移的列里 47% 属于这种（Step1 本来就是对的）。越过下界多看几行，
#: 真框就能完整成段、被认出来，`_frame_covers_top` 据此否决这次上移。
TOP_REFINE_BELOW = 6


def refine_top_by_frame(gray: np.ndarray, win: ColumnWindow,
                        probe: int = TOP_REFINE_PROBE, cov: float = TOP_REFINE_COV,
                        min_run: int = TOP_REFINE_MIN_RUN,
                        min_gap: int = TOP_REFINE_MIN_GAP) -> float:
    """列窗上界之上若还看得见**版框**（离上界 ≥ min_gap 行），把上界提到框的下沿。
    返回上移的行数（0 = 没动）。

    Step1 的上版框是整页一条直线；线拟合被首行字的顶边带偏时（bxgb p48/p54：整页首字
    顶边齐平，投影上是一条比厚框更「尖」的峰），这条线落在**首行字的顶边**而不是框上，
    离真框 12~22px。后果分两种，都是首字丢顶：
    - 首字比上界高（二十/三 这类），顶部整块不在列图里；
    - 首字顶边恰在上界，`column_border_trim` 见「贴着列图顶端的一条薄横」就按 a 档当框线
      削掉 6~16 行——二 变一、三 变二、六 丢点、冢 丢宀（用户审阅标的首字 seg_defect 16 条，
      13 条在这两页）。
    第一版只在「框与上界之间夹着字墨」时才动，漏掉第二种。列图本来就该从框的内缘起，
    框在上界之上多远都是错，所以只要看见框、离上界 ≥ min_gap 行就提；多出来的几行白
    由 Step3 的候选/`trim` 的 c 档照常处理。全书实测只有 p48/p54 两页触发。

    判据用满宽段（`TOP_REFINE_COV`），不用「像不像线」：二/三 的顶横再宽也到不了 0.85；
    上界之上是页边，除了框没有别的满宽墨。只对普通列（`border_top_in_column == 0`、非抬头）
    做，且只往上提、不往下推。下版框不需要镜像（探针全书 0 列，`BOTTOM_PAD` 早多开 40 行）。
    """
    if win.raised or win.border_top_in_column > 0.5 or win.top_y < probe:
        return 0.0
    # 往下多看 TOP_REFINE_BELOW 行：真框正压在 top_y 上时，只看上方会把它腰斩，
    # 反而去抓更上面的外框（见 TOP_REFINE_BELOW 的注释）。
    below = int(TOP_REFINE_BELOW)
    strip = warp_column(gray, win.left, win.right, win.top_y - probe, win.top_y + below)
    if strip.ndim == 3:
        strip = strip[:, :, 0]
    if strip.shape[1] < 20:
        return 0.0
    rows = (strip[:, 6:-6] < 128).mean(axis=1)
    full = rows >= cov
    # `top_y` 已经落在框上（或框刚好在它下面一点）——Step1 是对的，别动。
    if bool(full[max(0, probe - min_run):].any()):
        return 0.0
    runs: list[tuple[int, int]] = []
    a = None
    for i, v in enumerate(list(full) + [False]):
        if v and a is None:
            a = i
        if not v and a is not None:
            if i - a >= min_run:
                runs.append((a, i - 1))
            a = None
    if not runs:
        return 0.0
    # 只认 top_y 之上的段（下面那几行是为了看清真框才多取的，不能当搬迁目标）。
    runs = [r for r in runs if r[1] < probe]
    if not runs:
        return 0.0
    fb = runs[-1][1]
    delta = float(probe - 1 - fb)
    if delta < min_gap:
        return 0.0
    win.top_y -= delta
    win.border_top_y = win.top_y
    return delta


def warp_page_columns(gray: np.ndarray, result: BorderDetectionResult,
                       denoise: bool = False, **window_kwargs
                       ) -> list[tuple[ColumnWindow, np.ndarray]]:
    """整页逐列矫正，返回 `[(窗口, 列图), ...]`。Step 2 的正门。"""
    out = []
    for win in page_column_windows(result, **window_kwargs):
        img = warp_column(gray, win.left, win.right, win.top_y, win.bottom_y)
        if denoise:
            img = denoise_column(img)
        out.append((win, img))
    return out
