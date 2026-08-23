"""图块干净度分级：clean（完整、无残留）/ degraded（有残留或被切）。

**为什么要分层**（2026-08 策略）：上游切分做不到完美——正文页无标记率
vol01 78.9% / vol02 68.2%（管线手册 §1），总有一部分图块带着邻字残笔、
界行/版框残线，或者本字笔画被裁掉。归一化与聚类的目标相应分两档：
**在干净图块上必须做得非常好；在退化图块上能不崩、可标记**。评测就得
按这两层分开报，否则退化样本的失败会稀释干净层的信号，反之亦然。

分级在**原始灰度图块**上做。图块 = bbox + padding，要害是把「核心区」
（bbox 内）与 padding 带分开看——**邻字探进 padding 带是常态**（上下邻字
本来就近），人工标 clean 的图块照样带着它；第一版不分区，把这当残留，
在 55 个人工 clean 实例上误报了近半。判据：

- `truncated`（被切）：主体连通体压在**图块外边界**上的墨 ≥ `edge_ink_px`。
  完整的字连 padding 都不该穿透；穿透了说明裁切线从笔画中间过。
- `residue`（残留）：**从图块边缘伸进核心区**的非主体连通体——须同时
  (a) 碰到图块外边界、(b) 核心区内的墨 ≥ `foreign_core_px`。
  两个条件缺一不可：只在 padding 带里待着的邻字（碰边但不进核心区）
  是常态；而**汉字本身就是多连通体的**（卷、此、門、百……部件互不相连），
  核心区里的非主体连通体多半是本字自己的部件——第二版没加 (a)，
  55 个人工 clean 实例误报了 21 个，全是这种。

二值化用 Otsu，不用归一化的 Sauvola——分级判据要给归一化当评测分层用，
不能与被测算法同源（making-datasets.md 第四步第 4 条的同一条纪律）。

**校准**（2026-08-23，对着 `char-segmentation/instances` 人工 quality 标签
第九轮 62 个实例扫）：`edge_ink_px=14 / foreign_core_px=25` 时缺陷检出 5/7、
clean 误报 2/55。阈值在 10~24 / 15~60 区间内数字几乎不动，不是精调出来的。

已知盲区（漏掉的那 2 个缺陷就是它们，写进各数据集 known_limitation）：

- 污染**整体落在 bbox 内部、不碰图块边界**（bbox 过高吃进下一字的头），
  与本字自己的部件几何上无法区分；
- 图内自洽的截断：只切到字的下半，但剩下的部分看起来像个完整的字，
  只有拿着页面上下文才能判——这类本来就只有人工能标。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

EDGE_INK_PX = 14         # 主体压图块外边界的墨（像素数）达到此值 → truncated
FOREIGN_CORE_PX = 25     # 碰边连通体落在核心区内的墨（像素数）→ residue
MIN_MAIN_AREA = 20       # 主体连通体最小面积，低于此视为空图块
DEFAULT_MARGIN = 0.075   # 不知道确切 padding 时的核心区边距（padding_ratio≈0.08）


@dataclass
class CropQuality:
    tier: str                 # "clean" | "degraded" | "empty"
    truncated: bool
    residue: bool
    edge_ink_px: int          # 主体压在图块外边界上的墨（像素数）
    n_foreign: int            # 闯进核心区的外来连通体个数
    foreign_core_px: int      # 外来连通体落在核心区内的墨合计
    main_area: int

    def to_dict(self) -> dict:
        return {"tier": self.tier, "truncated": self.truncated,
                "residue": self.residue, "edge_ink_px": self.edge_ink_px,
                "n_foreign": self.n_foreign, "foreign_core_px": self.foreign_core_px}


def _binarize(gray: np.ndarray) -> np.ndarray:
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # <=：不少图块的灰度源本来就是二值图（s6_binarize），Otsu 对 {0,255}
    # 双值分布返回阈值 0，用 < 会把全部墨判空。
    return (gray <= thr).astype(np.uint8)


def assess_crop(gray: np.ndarray,
                margins: tuple[int, int] | None = None,
                edge_ink_px: int = EDGE_INK_PX,
                foreign_core_px: int = FOREIGN_CORE_PX) -> CropQuality:
    """原始灰度图块 → 干净度分级。

    margins=(纵边距, 横边距) 是核心区（bbox）到图块边缘的像素距离，可由
    index.jsonl 的 bbox 与 height/width 之差算出；不给就按 DEFAULT_MARGIN 估。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = _binarize(gray)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return CropQuality("empty", False, False, 0, 0, 0, 0)

    areas = stats[1:, cv2.CC_STAT_AREA]
    main = int(np.argmax(areas)) + 1
    main_area = int(areas[main - 1])
    if main_area < MIN_MAIN_AREA:
        return CropQuality("empty", False, False, 0, 0, 0, main_area)

    h, w = binary.shape
    if margins is None:
        my, mx = int(round(h * DEFAULT_MARGIN)), int(round(w * DEFAULT_MARGIN))
    else:
        my, mx = margins
    my = min(max(my, 0), max(h // 2 - 1, 0))
    mx = min(max(mx, 0), max(w // 2 - 1, 0))

    border = np.zeros((h, w), dtype=bool)
    border[0, :] = border[-1, :] = True
    border[:, 0] = border[:, -1] = True
    edge_ink = int(np.count_nonzero((labels == main) & border))

    core = np.zeros((h, w), dtype=bool)
    core[my:h - my, mx:w - mx] = True
    n_foreign = 0
    core_total = 0
    for i in range(1, n):
        if i == main:
            continue
        comp = labels == i
        if not np.count_nonzero(comp & border):
            continue                      # 不碰边 → 本字自己的部件
        in_core = int(np.count_nonzero(comp & core))
        core_total += in_core
        if in_core >= foreign_core_px:
            n_foreign += 1

    truncated = edge_ink >= edge_ink_px
    residue = n_foreign > 0
    tier = "degraded" if (truncated or residue) else "clean"
    return CropQuality(tier, truncated, residue, edge_ink,
                       n_foreign, core_total, main_area)
