"""合成刻本数据生成器 —— 测试与 benchmark 的基础设施。

两种字形来源：
- render_char(): 用繁体 CJK 字体（TTF）渲染真实汉字（benchmark 用，需字体文件）
- synthetic_glyph(): 随机笔画组合的伪字形（单测用，零外部依赖）

刻本磨损模拟 degrade()：腐蚀/膨胀、笔画断裂、边缘噪声、着墨不匀。
同一字的多个实例 = 同一基准字形 + 不同磨损 → 精确模拟"同版同字"假设。
"""

from __future__ import annotations

import random

import cv2
import numpy as np

from .normalize import NORM_SIZE


def render_char(char: str, font_path: str, size: int = NORM_SIZE,
                canvas: int = 96) -> np.ndarray:
    """用 TTF 字体渲染单字 → S×S uint8 {0,1}（1=墨迹）。需要 Pillow + 字体文件。"""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, int(canvas * 0.8))
    img = Image.new("L", (canvas, canvas), 255)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), char, font=font)
    x = (canvas - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = (canvas - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((x, y), char, fill=0, font=font)
    arr = np.asarray(img)
    binary = (arr < 128).astype(np.uint8)
    resized = cv2.resize(binary * 255, (size, size), interpolation=cv2.INTER_AREA)
    return (resized > 127).astype(np.uint8)


def synthetic_glyph(rng: random.Random, size: int = NORM_SIZE,
                    n_strokes: int = 6) -> np.ndarray:
    """随机"笔画"组合的伪字形（横竖撇捺的随机直线段）。

    单测用：不同 seed 生成的字形彼此差异大（模拟不同字），
    同一字形 + degrade() 模拟同字的不同印次。
    """
    img = np.zeros((size, size), dtype=np.uint8)
    margin = size // 8
    for _ in range(n_strokes):
        x1 = rng.randint(margin, size - margin)
        y1 = rng.randint(margin, size - margin)
        # 偏向横竖笔画（汉字特征）
        if rng.random() < 0.5:
            x2, y2 = rng.randint(margin, size - margin), y1 + rng.randint(-4, 4)
        else:
            x2, y2 = x1 + rng.randint(-4, 4), rng.randint(margin, size - margin)
        thickness = rng.randint(2, 4)
        cv2.line(img, (x1, y1), (x2, y2), 1, thickness)
    return img


def degrade(glyph: np.ndarray, rng: random.Random,
            wear: float = 0.5) -> np.ndarray:
    """刻本磨损模拟。wear ∈ [0, 1] 控制强度。

    - 随机腐蚀/膨胀（着墨浓淡）
    - 笔画断裂（随机细线擦除）
    - 边缘噪声（椒盐 + 小连通斑点）
    """
    out = glyph.copy()
    size = out.shape[0]

    # 着墨浓淡：随机腐蚀或膨胀一次（wear=0 时不做任何退化）
    if rng.random() < wear:
        kernel = np.ones((2, 2), dtype=np.uint8)
        if rng.random() < 0.5:
            out = cv2.erode(out, kernel)
        else:
            out = cv2.dilate(out, kernel)

    # 笔画断裂：随机短细线擦除
    n_breaks = int(wear * 3 * rng.random() + 0.5)
    for _ in range(n_breaks):
        x = rng.randint(0, size - 1)
        y = rng.randint(0, size - 1)
        dx = rng.randint(-5, 5)
        dy = rng.randint(-5, 5)
        cv2.line(out, (x, y), (x + dx, y + dy), 0, 1)

    # 边缘噪声：稀疏椒盐
    n_noise = int(wear * size * 0.5)
    for _ in range(n_noise):
        x = rng.randint(0, size - 1)
        y = rng.randint(0, size - 1)
        out[y, x] = rng.randint(0, 1)

    return out


def make_dataset(n_chars: int, n_per_char: int, seed: int = 0,
                 wear: float = 0.5, font_path: str | None = None,
                 charset: str | None = None
                 ) -> tuple[np.ndarray, np.ndarray]:
    """生成合成聚类数据集。

    Returns:
        patches: (n_chars * n_per_char, S, S) uint8 {0,1}
        labels:  (n_chars * n_per_char,) int —— 真值字 id
    """
    rng = random.Random(seed)
    bases: list[np.ndarray] = []
    if font_path and charset:
        for ch in charset[:n_chars]:
            bases.append(render_char(ch, font_path))
    else:
        for i in range(n_chars):
            bases.append(synthetic_glyph(random.Random(seed * 10007 + i)))

    patches, labels = [], []
    for label, base in enumerate(bases):
        for _ in range(n_per_char):
            patches.append(degrade(base, rng, wear=wear))
            labels.append(label)
    return np.stack(patches), np.asarray(labels)


def purity(members_by_cluster: list[list[int]], labels: np.ndarray) -> float:
    """聚类纯度：Σ 簇内多数标签数 / 总实例数。保守聚类的硬指标。"""
    total = correct = 0
    for members in members_by_cluster:
        if not members:
            continue
        lab = labels[np.asarray(members)]
        counts = np.bincount(lab)
        correct += int(counts.max())
        total += len(members)
    return correct / max(1, total)


def fragmentation(members_by_cluster: list[list[int]],
                  labels: np.ndarray) -> float:
    """碎片率：每个真实字平均被拆成的簇数（越接近 1 越好）。"""
    clusters_per_label: dict[int, set[int]] = {}
    for ci, members in enumerate(members_by_cluster):
        for m in members:
            clusters_per_label.setdefault(int(labels[m]), set()).add(ci)
    if not clusters_per_label:
        return 0.0
    return sum(len(v) for v in clusters_per_label.values()) / len(clusters_per_label)
