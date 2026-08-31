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

import cv2
import numpy as np

from .border_geometry import HLine, VLine


def warp_column(gray: np.ndarray, left: VLine, right: VLine,
                 top_y: float = 0.0, bottom_y: float | None = None) -> np.ndarray:
    """把 `left`/`right` 两条竖直边线之间的列矫正成竖直矩形灰度图。

    `left`/`right` 是新坐标系（右上角原点）下的 `VLine`；`top_y`/`bottom_y`
    也是新坐标系的 y（默认整页高度，通常应传 Step 1 输出的上下版框在该
    列位置的 y 值，而不是整页边缘——版框外的页边留白不属于这一列）。

    输出矩形的宽度取 `left`/`right` 在 `top_y`/`bottom_y` 两处间距的较大者
    （避免两端宽度不一致时把内容压扁）；高度取 `bottom_y - top_y`。输出图
    沿用标准图像坐标系（左上角原点）——矫正之后的列图不再是页面的一部分，
    没必要维持"右上角原点"这个页面级约定。
    """
    h, w = gray.shape[:2]
    if bottom_y is None:
        bottom_y = float(h - 1)
    if bottom_y <= top_y:
        raise ValueError(f"bottom_y({bottom_y}) must be > top_y({top_y})")

    def to_old_x(vline: VLine, y_new: float) -> float:
        return (w - 1) - vline.x_at(y_new)

    lx_top, rx_top = to_old_x(left, top_y), to_old_x(right, top_y)
    lx_bot, rx_bot = to_old_x(left, bottom_y), to_old_x(right, bottom_y)

    out_w = int(round(max(abs(rx_top - lx_top), abs(rx_bot - lx_bot))))
    out_h = int(round(bottom_y - top_y))
    if out_w <= 0 or out_h <= 0:
        raise ValueError(f"warped column size invalid: {out_w}x{out_h}")

    src = np.array([[lx_top, top_y], [rx_top, top_y],
                     [rx_bot, bottom_y], [lx_bot, bottom_y]], dtype=np.float32)
    dst = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, m, (out_w, out_h),
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


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


def column_bounds(top: HLine, bottom: HLine,
                   head_raise_inner_y: float | None = None) -> tuple[float, float]:
    """给 `warp_column` 算 `top_y`/`bottom_y` 的**标准调用约定**。

    版框是斜的（实测上版框斜率最大 0.032），`HLine` 只是一条线，"这一列的
    上下界在哪"取决于沿这条线的哪个 x 取值——接口里没写死，这个函数把约定
    固化下来：**一律取页面右端锚点 `x=0`**（即 `HLine.y_at_right`），不随列
    位置变化。

    代价是已知的、如实记着：越靠左的列，这个锚点离该列真实版框越远——14 页
    126 列实测，`y_at(0)` 与"该列中心处的版框 y"相差 top 均值 14.6px / 最大
    60.5px、bottom 均值 8.7px / 最大 26.5px（最差都在 vol01/47、33 这类上版框
    斜率大的页面的最左几列）。也就是说最左列的矫正图上端可能比真实版框低
    60px，会切进首字。这是选定约定时明知的取舍，不是 bug；要改口径就改这
    一个函数，`warp_column` 不动。

    抬头列传 `head_raise_inner_y`（`BorderDetectionResult.head_raise` 里该列
    的 `inner_y`；同一列有多级台阶时传**最小的那个**，即最高的一级），上界
    直接用它——抬头字顶到主版框以上，用主版框会把抬头字齐腰切掉。抬头框本身
    是局部量、不贯穿全页，没有"沿哪个 x 取值"的问题。
    """
    top_y = float(top.y_at(0.0)) if head_raise_inner_y is None else float(head_raise_inner_y)
    return top_y, float(bottom.y_at(0.0))


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
                      max_rule_frac: float = 0.15) -> tuple[int, int]:
    """找矫正图里**文字带的左右边界** `(x_left, x_right)`（半开区间，右端不含）。

    边界外侧就是残余界行。判据：界行是一条贯穿整列的竖直墨线，在
    `column_profile` 上表现为紧贴边缘、由高到低衰减的一段；界行和字身之间
    有一道墨量的**谷**。所以从两端各自往里扫——

    1. 边缘那一格墨占比 `<= edge_ink_eps` 就直接收手：这一侧压根没有界行
       （版心侧被装订切掉了），别动。
    2. 否则在 `max_rule_frac * 宽度` 的窗口里找**最低点**，边界取
       **第一个降到「最低点 + `plateau_tol`」的位置**——也就是界行衰减到谷底
       的那一格。

    第 2 步这个"扫到窗口最低点"的写法是拿 32 列人裁金标标定出来的
    （`char-segmentation/column-warp`）。**上一版是"先吃墨占比 >= 0.35 的
    界行本体、再吃 >= 阈值的裙边"，两头都会翻车，已撤销**：

    * 界行被残余倾斜抹糊时（vol01/47 那几列，整段墨占比只有 0.10~0.12）
      够不到 0.35，第一步就判成"这侧没界行"，整条界行原样留在带里（欠 30px）；
    * 带内有一道贯穿全高的淡竖痕时（vol01/33 c5 右侧，界行降到 0.01 之后
      **永远停在 0.01**、不再归零），裙边判据一路吃到 15% 上限，切进字身 21px。

    "扫到最低点"对两者都成立：糊掉的界行照样有谷（0.11→0.00），淡竖痕的
    0.01 平台**本身就是窗口最低点**，扫到它就停，不会继续啃。

    两个阈值的默认值是在 32 列金标上**扫曲线**定的，不是挑的单点：
    `plateau_tol` 取 0.002 时命中 57/64、但会切进字身 23px；取 0.005 时命中
    56/64、**切字 0px**（欠量 39px）；取 0.01 直接掉到 35/64。按"宁可留残墨
    也不切字"取 0.005 这个零切字点，少的那 1 条命中是自愿付的价。
    `edge_ink_eps` 在 0.01/0.02/0.04 之间只影响欠量（39/51/51px），不影响
    切字，取最小的 0.01。`max_rule_frac` 这个上限也保留着——留下的残墨
    Step4 的字框收缩还有一道防线，切掉的字谁也补不回来。
    """
    prof = column_profile(warped_gray, ink_threshold)
    n = len(prof)
    limit = max(1, min(int(round(max_rule_frac * n)), n // 2))

    def scan(order: np.ndarray) -> int:
        window = prof[order[:limit]]
        if window[0] <= edge_ink_eps:
            return 0                        # 这一侧没有界行，别动
        floor = float(window.min())
        return int(np.argmax(window <= floor + plateau_tol))

    idx = np.arange(n)
    left = scan(idx)
    right = n - scan(idx[::-1])
    if left >= right:                        # 判据失效，原样返回，绝不返回空带
        return 0, n
    return left, right


def strip_column_rules(warped_gray: np.ndarray, ink_threshold: int = 128,
                        rule_coverage: float = 0.35, skirt_coverage: float = 0.12,
                        max_rule_frac: float = 0.15) -> np.ndarray:
    """把矫正图两侧的残余界行抹成背景白，返回**同尺寸**的新图。

    抹白而不是裁掉——矫正图的局部坐标系是 Step3(`row-boundaries` 金标)、
    Step4 共用的锚，裁一刀所有挂在上面的坐标就全漂了。要裁的调用方自己
    按 `column_text_band` 的返回值裁。
    """
    left, right = column_text_band(warped_gray, ink_threshold, rule_coverage,
                                    skirt_coverage, max_rule_frac)
    out = warped_gray.copy()
    out[:, :left] = 255
    out[:, right:] = 255
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
        if float(p[blank:blank + bar_probe].max()) >= bar_coverage:
            return blank + glue_px, "b"        # 版框粘着首字，只削一点
        return (glue_px, "b") if blank == 0 else (0, "c")

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
