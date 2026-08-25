"""M2 图块归一化：灰度图块 → 标准 S×S 二值字形图。

流程（设计文档 6.1）：
1. Sauvola 局部二值化（与 s6 预处理解耦，参数独立）
2. 去边缘毛刺：删除贴边且面积过小的连通域（界行/相邻字残留）
3. 墨迹外接框等比缩放 + 质心居中，四周留白
4. 输出 uint8 {0,1} 二值图（1=墨迹）

**笔宽归一（stroke_normalize）2026-08-24 起默认不做**，理由见该函数的
文档字符串——一句话：它是为刚性 F1 判据抗着墨浓淡而加的，现在的
elastic 软覆盖判据本来就不吃这一套，它反而把 已/巳 那类开口糊死。
"""

from __future__ import annotations

import cv2
import numpy as np

NORM_SIZE = 64          # 归一化边长 S
MARGIN_RATIO = 0.12     # 四周留白比例
NOISE_AREA = 6          # 贴边小连通域面积阈值（像素）
SAUVOLA_WINDOW = 31
SAUVOLA_K = 0.2


def sauvola_binarize(gray: np.ndarray, window: int = SAUVOLA_WINDOW,
                     k: float = SAUVOLA_K) -> np.ndarray:
    """Sauvola 局部阈值二值化。返回 uint8 {0,1}，1=墨迹（暗像素）。"""
    g = gray.astype(np.float64)
    mean = cv2.boxFilter(g, ddepth=-1, ksize=(window, window),
                         borderType=cv2.BORDER_REPLICATE)
    sq_mean = cv2.boxFilter(g * g, ddepth=-1, ksize=(window, window),
                            borderType=cv2.BORDER_REPLICATE)
    std = np.sqrt(np.maximum(sq_mean - mean * mean, 0.0))
    R = 128.0
    thresh = mean * (1.0 + k * (std / R - 1.0))
    return (g < thresh).astype(np.uint8)


def remove_edge_specks(binary: np.ndarray, noise_area: int = NOISE_AREA,
                       margins: tuple[int, int] | None = None) -> np.ndarray:
    """删除切分/裁切残留（P3 重写，2026-08-23）。

    旧判据（贴边 + shallow_tb/lr + 贴边细线）被废除：它既**漏**（不贴边的
    版框线/界行线一条都够不着——golden 集三轮切分版本下 4 个缺陷同根因），
    又**误杀**（「二」贴底边的底横被 shallow_tb 当残留删掉，实锤实例
    vol02:157:2:4 直接毒化字形匹配）。

    新判据只删**无歧义的非笔画**，厚组件的格位归属是切分层（F 步
    component_owner）的职责，不在这里重复判断：

    1. **贴边小噪点**：贴边且面积 < noise_area（原规则保留）；
    2. **细线（位置无关）**：平均厚度 ≤ max(3, 0.045×min(h,w)) 且细长
       （长边 ≥ 0.5×对应边长）的组件——版框/界行线厚 2~5px，本书笔画厚
       8~14px，两个分布不重叠（分布重叠就别调阈值，这里不重叠才敢用）。
       护栏：非最大组件，且最大组件面积 ≥ 1.2× 它——保护「一」（自己就
       是主体）与 二/三（笔画厚，根本进不了细线档）；
    3. **padding 带碎屑**：墨 ≥80% 落在 padding 带（核心区 = bbox，
       margins 给出带宽，缺省按 7.5% 估）且面积 < 0.25× 最大组件——
       邻字探进来的小残片。大块残片**不删**（可能是被切的本字笔画，
       归属该由切分层判）。
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    h, w = binary.shape
    if margins is None:
        my, mx = int(round(h * 0.075)), int(round(w * 0.075))
    else:
        my, mx = margins
    my = min(max(my, 0), max(h // 2 - 1, 0))
    mx = min(max(mx, 0), max(w // 2 - 1, 0))

    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(areas.max())
    thin_cap = max(3.0, 0.045 * min(h, w))

    core = np.zeros((h, w), dtype=bool)
    core[my:h - my, mx:w - mx] = True

    out = binary.copy()
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches = (x == 0 or y == 0 or x + bw >= w or y + bh >= h)
        if touches and area < noise_area:                      # 规则 1
            out[labels == i] = 0
            continue
        if area == largest:
            continue
        long_side = max(bw, bh)
        thickness = area / max(1, long_side)
        is_line = (thickness <= thin_cap
                   and ((bh >= 0.5 * h and bw < bh) or (bw >= 0.5 * w and bh < bw)))
        if is_line and largest >= 1.2 * area:                  # 规则 2
            out[labels == i] = 0
            continue
        comp = labels == i
        in_core = int(np.count_nonzero(comp & core))
        if area - in_core >= 0.8 * area and area < 0.25 * largest:   # 规则 3
            out[labels == i] = 0
    return out


def _drop_stray_components(binary: np.ndarray,
                           keep_ink_ratio: float = 0.98) -> np.ndarray:
    """稳健化墨迹：删掉**落在字身之外**的小残片（邻字一角、界行线、噪点），
    防止外接框被残片撑大。

    两步，缺一不可：

    1. 先按面积从大到小累计到 `keep_ink_ratio`，得到「字身」；
    2. **再把质心落在字身外接框内的小块收回来**——它们是本字自己的
       点、短横、断开的笔画，不是残片。

    第 2 步是 2026-08-25 补的。此前只有第 1 步，是个纯质量判据：笔画密的
    字里一个「丶」占不到总墨的 2%，于是被当残片删掉。拿出库裁决台那
    152 块扫，53 个被删的连通体里 **40 个的质心落在字身框内**——按/削/資/
    量/罔/勝/臨/隨/明 的点和短横，全是真笔画。用户在裁决台上就是这么发现的
    （「把一些特别短的笔画，比方说短横和点都给变没了」）。剩下 13 个落在
    框外（舜左边那条界行线之类），正是这条判据本来要删的东西。

    质心在框内不等于一定是本字的笔画——bbox 过高吃进下一字的头、且那截
    墨恰好落在框内，仍然收不回来也删不掉（`crop_quality` 模块头里记的同一个
    已知盲区）。但「框内的小块一律留着」比「小块一律删掉」错得轻：多留一个
    残点只让外接框稍胖，删掉一个「丶」是把字改了。
    """
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8)
    if n <= 2:
        return binary
    areas = stats[1:, cv2.CC_STAT_AREA]
    order = np.argsort(-areas)
    total = areas.sum()
    keep: set[int] = set()
    acc = 0
    for k in order:
        keep.add(k + 1)
        acc += areas[k]
        if acc >= total * keep_ink_ratio:
            break
    # 字身外接框（只由第 1 步留下的块决定）
    body = np.isin(labels, list(keep))
    ys, xs = np.nonzero(body)
    if len(xs):
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        for i in range(1, n):
            if i in keep:
                continue
            cx, cy = centroids[i]
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                keep.add(i)
    out = binary.copy()
    drop_mask = ~np.isin(labels, list(keep)) & (binary > 0)
    out[drop_mask] = 0
    return out


def ink_bbox(binary: np.ndarray) -> tuple[int, int, int, int] | None:
    """墨迹外接框 (x0, y0, x1, y1)，无墨迹返回 None。x1/y1 为开区间。"""
    ys, xs = np.nonzero(binary)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def normalize_patch(gray: np.ndarray, size: int = NORM_SIZE,
                    margin_ratio: float = MARGIN_RATIO,
                    noise_area: int = NOISE_AREA,
                    stroke_width: int | None = None,
                    margins: tuple[int, int] | None = None) -> np.ndarray:
    """灰度图块 → S×S uint8 {0,1} 归一二值图。

    墨迹外接框等比缩放到内容区（size × (1 - 2*margin)），
    再平移使墨迹质心对准图心（clamp 保证不出界）。
    空图块（无墨迹）返回全零。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = sauvola_binarize(gray)
    binary = remove_edge_specks(binary, noise_area, margins=margins)

    binary = _drop_stray_components(binary)
    bbox = ink_bbox(binary)
    out = np.zeros((size, size), dtype=np.uint8)
    if bbox is None:
        return out
    x0, y0, x1, y1 = bbox
    crop = binary[y0:y1, x0:x1]

    content = max(1, int(round(size * (1.0 - 2.0 * margin_ratio))))
    ch, cw = crop.shape
    # 受限各向异性缩放：以等比为基准，每轴允许 ±20% 拉伸把外接框
    # 撑满内容区 —— 抵消切分抖动造成的 bbox 纵横比噪声，
    # 又不至于把「一/亅」这类极端纵横比的字拉成一样。
    scale = content / max(ch, cw)
    sy = min(max(content / ch, scale * 0.8), scale * 1.25)
    sx = min(max(content / cw, scale * 0.8), scale * 1.25)
    nh = max(1, min(size, int(round(ch * sy))))
    nw = max(1, min(size, int(round(cw * sx))))
    resized = cv2.resize(crop.astype(np.uint8) * 255, (nw, nh),
                         interpolation=cv2.INTER_AREA)
    resized = (resized > 127).astype(np.uint8)

    # 先按几何中心摆放，再按质心微调
    ys, xs = np.nonzero(resized)
    if len(xs) == 0:
        return out
    cy, cx = float(ys.mean()), float(xs.mean())
    top = int(round(size / 2.0 - cy))
    left = int(round(size / 2.0 - cx))
    top = min(max(top, 0), size - nh)
    left = min(max(left, 0), size - nw)
    out[top:top + nh, left:left + nw] = resized
    if stroke_width:
        out = stroke_normalize(out, stroke_width)
    return out


def _thin_once(img: np.ndarray, step: int) -> np.ndarray:
    """Zhang-Suen 细化的一个子迭代（向量化）。img: uint8 {0,1}。"""
    p = np.pad(img, 1)
    p2 = p[:-2, 1:-1]; p3 = p[:-2, 2:]; p4 = p[1:-1, 2:]
    p5 = p[2:, 2:];   p6 = p[2:, 1:-1]; p7 = p[2:, :-2]
    p8 = p[1:-1, :-2]; p9 = p[:-2, :-2]
    neigh = [p2, p3, p4, p5, p6, p7, p8, p9]
    B = sum(n.astype(np.int32) for n in neigh)
    ring = neigh + [p2]
    A = sum(((ring[i] == 0) & (ring[i + 1] == 1)).astype(np.int32)
            for i in range(8))
    if step == 0:
        cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
    else:
        cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
    remove = (img == 1) & (B >= 2) & (B <= 6) & (A == 1) & cond
    out = img.copy()
    out[remove] = 0
    return out


def skeletonize(binary: np.ndarray, max_iter: int = 20) -> np.ndarray:
    """Zhang-Suen 骨架化。输入/输出 uint8 {0,1}。"""
    img = binary.astype(np.uint8)
    for _ in range(max_iter):
        nxt = _thin_once(_thin_once(img, 0), 1)
        if np.array_equal(nxt, img):
            break
        img = nxt
    return img


def stroke_normalize(binary: np.ndarray, stroke_width: int = 3) -> np.ndarray:
    """笔宽归一：骨架化 + 统一膨胀到固定笔宽。**默认不再调用**（2026-08-24）。

    当初的理由：刻本不同印次着墨浓淡不同（同字笔画可差 2 倍宽），而当时的
    判据是**刚性墨迹 F1**，对笔宽极敏感；归一到统一笔宽后，同字 F1 主要
    反映骨架形状差异。

    为什么撤掉：判据早已换成 elastic（软覆盖 + 分块弹性对齐，verify.py），
    它按「到对方墨迹的距离」给分——粗笔多出来的墨就贴在细笔旁边，本来就
    几乎不扣分。也就是说它抗着墨浓淡的那份功劳现在是白拿的，代价却实打实：

    - 膨胀到 3px 会把 已/巳、日/曰 这类**开口/缝隙直接糊死**，那正是
      glyph-match/triplets hard 子集的主要失败形态；
    - 它的「副作用」——桥接 1~2px 笔画断裂——是**把断口盖住而不是修好**
      （实测 37 张 golden 里 4 张如此）。断是上游二值化留下的，该在上游修。

    撤掉后实测（参数一个没动，tau1.5/blk16/loc1）：
      triplets hard 排序      0.6842 → 0.7632（control 1.000 不动）
      glyph-match/pairs 主指标 recall 0.0807 → 0.1130，precision 仍 ≥0.999
      其中笔画最密的一档 recall 0.0101 → 0.0155

    函数保留：`stroke_width=3` 仍可显式传入（旧判据对照、单测用）。
    """
    skel = skeletonize(binary)
    if not skel.any():
        return skel
    k = max(1, stroke_width)
    kernel = np.ones((k, k), dtype=np.uint8)
    return cv2.dilate(skel, kernel)


def soft_patch(binary: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """归一二值图 → 轻度模糊的 float32 图（特征提取用，抗锯齿/微形变）。"""
    f = binary.astype(np.float32)
    return cv2.GaussianBlur(f, ksize=(0, 0), sigmaX=sigma)
