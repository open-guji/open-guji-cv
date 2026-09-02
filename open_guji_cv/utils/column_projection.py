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


def column_profile(warped_gray: np.ndarray, ink_threshold: int = 128) -> np.ndarray:
    """矫正图**沿竖直方向的投影**：长度 = 图宽，每个 x 上的墨占比（0~1）。

    这是 `char-segmentation/column-warp` 金标的核心量——矫正对了的话，这条
    曲线两端应该是空白（界行已清除），中间是字身墨；矫正歪了的话，界行
    残留会从"又窄又高的尖峰"摊成"又宽又矮的鼓包"（一条直线歪了 δ px 就在
    投影上抹开 δ px），所以曲线的形状本身也是残余倾斜的读数。
    """
    return (warped_gray < ink_threshold).astype(np.float64).mean(axis=0)


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
    n = len(prof)
    limit = max(1, min(int(round(max_rule_frac * n)), n // 2))

    def scan(order: np.ndarray) -> int:
        window = prof[order[:limit]]
        if window[0] > edge_ink_eps:                 # 贴边档
            floor = float(window.min())
            return int(np.argmax(window <= floor + plateau_tol))
        # 内缩档：在自己的宽窗口里找**峰值最高的那一段**墨，看它是不是孤立窄条。
        # 不能取"第一段"——去噪之后仍有零星 1~2% 的麻点，一段麻点就把前导空白
        # 截断了（vol01/47 c4 实测踩过：真正的界行条在 x=22~30、峰 0.98，却被
        # x=9 处一个 0.013 的麻点挡住，判成"没有条"）。
        wide = prof[order[:max(1, min(int(round(inset_look_frac * n)), n // 2))]]
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


def column_border_trim(warped_gray: np.ndarray, band: tuple[int, int] | None = None,
                        ink_threshold: int = 128, ink_eps: float = 0.02,
                        border_max_rows: int = 30, inset_look: int = 70,
                        glue_px: int = 3, bar_probe: int = 8,
                        bar_coverage: float = 0.65, inset_min_peak: float = 0.15
                        ) -> tuple[tuple[int, str], tuple[int, str]]:
    """上下版框残墨该削掉几行 —— 返回 `((top_px, top_case), (bottom_px, bottom_case))`。

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

    def one(p: np.ndarray) -> tuple[int, str]:
        blank = 0
        while blank < len(p) and p[blank] <= ink_eps:
            blank += 1
        if blank > inset_look or blank >= len(p):
            return 0, "c"                     # 边缘一大片空白，里面是正文
        run = blank
        while run < len(p) and p[run] > ink_eps:
            run += 1
        thick = run - blank
        if thick <= border_max_rows:           # 一条薄横线
            if blank == 0:
                return run, "a"                 # 贴着边缘，削掉几行无害
            # 内缩档：要求这条线本身有像样的墨，否则那是噪点不是版框
            # （vol01/142 c6 上端：空白 30 行后 3 行、墨占比只有 0.03，
            #   人裁的结论是"没残墨"，早先按 d 档削了 33 行是假阳性）
            if float(p[blank:run].max()) >= inset_min_peak:
                return run, "d"
            return 0, "c"
        # 厚墨段：是版框粘着字，还是**压根就是字**？看起始陡度——版框线一上来
        # 就满宽（头 3~4 行冲到 0.74~0.93），字的顶/底边必然是细的、缓起。
        # 这一条以前只在内缩档用，贴边档一律判 b（粘连），结果把"末字顶到
        # 边缘"整批误报成版框：64 条端裁决实测错 7 条，全是底端的 b→金标 none。
        if float(p[blank:blank + bar_probe].max()) >= bar_coverage:
            return blank + glue_px, "b"        # 版框粘着字，只削一点
        return 0, "c"                           # 是字不是版框，什么都不削

    return one(prof), one(prof[::-1])


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
    (top_px, top_case), (bot_px, bot_case) = column_border_trim(
        no_rules, band, ink_threshold=ink_threshold, **kwargs)
    out = no_rules.copy()
    if top_px:
        out[:top_px] = 255
    if bot_px:
        out[out.shape[0] - bot_px:] = 255
    return out, {"band": band,
                  "top": {"px": top_px, "case": top_case},
                  "bottom": {"px": bot_px, "case": bot_case}}


# ── 逐列的矫正窗口 ───────────────────────────────────────────

BODY_PAD = 0.0     # 普通列在版框之外额外留的余量


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
                         body_pad: float = BODY_PAD) -> list[ColumnWindow]:
    """整页每一列的矫正窗口——上下界**逐列**算（委派给 `column_bounds`），
    抬头列自动用抬头框的内边框当上界。

    `result` 直接用 `border_geometry.detect_borders()` 的输出：`head_raise`
    已经由 `detect_head_raise()` 填好，调用方不需要再给抬头先验。同一列若有
    多级台阶，取 `inner_y` **最小**的那个（最高的一级）。
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
        bottom_y += body_pad
        top_y = max(0.0, min(top_y, btop))
        bottom_y = min(float(result.height - 1), max(bottom_y, bbot))
        out.append(ColumnWindow(
            col=col, left=left_v, right=right_v,
            top_y=float(top_y), bottom_y=float(bottom_y),
            border_top_y=float(btop), border_bottom_y=float(bbot),
            raised=raised_top is not None,
            head_raise_inner_y=None if raised_top is None else float(raised_top)))
    return out


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
