# -*- coding: utf-8 -*-
"""整页二值副本：灰度扫描 → 一套 {0,255} 的页图，落盘给下游与人裁共用。

## 为什么要有这一层

用户 2026-09-16 定的口径：**最后进字形库的一定是二值的，灰度值会干扰**；
审阅时看二值的也更准（人判「这块图能不能进库」，看到的就该是库里那个形）。

现状是「**每个消费点各自二值化**」：

| 消费点 | 怎么二值 |
|---|---|
| `glyph_db._unpng` | `img < 128` 固定阈 |
| `normalize_patch` | Sauvola 31/k（在 64×64 小图上） |
| `to_canonical` | Sauvola 31/k（定 bbox 用） |
| Step1/2 的 `ink_threshold` | `< 128` 固定阈 |
| **库里存的** | **灰度**（189~198 个灰阶） |

问题不在「没二值」，而在**各二值各的**：同一个字块在检索、匹配、展示三处
可能得到三张不同的二值图；而库里存灰度，等于把「用哪把尺子」推迟到每次读取，
换一套归一协议就得重播全库。

这一层把它统一到**页级**：一次把整页二值化好落盘，`raw_bin_page` 给下游取用，
控制台可以同一个坐标既给二值图也给原图（`?src=bin|raw`）。

## 为什么是 Sauvola 而不是固定阈

北行日錄刻本实测（p20，界行真值 13 条）：

| 方法 | 框内墨占比 | 界行存活 |
|---|---|---|
| `< 128` | 0.144 | **6 / 13** |
| Otsu | 0.161 | 10 / 13 |
| **Sauvola 31/0.2** | 0.164 | **13 / 13** |（当时的 k，2026-09-16 已降到 0.10）
| Sauvola 101/0.1 | 0.195 | 13 / 13 |

界行是**浅灰细线**（沿线 p50 ≈150，纸 ≈205），固定阈 128 砍掉一半——这正是
Step1 当初不得不上网格模式的原因（见 `01-step2界行识别.md`）。Sauvola 是局部
阈值，淡线旁边的纸更淡，所以留得住。

窗口取 31（与 `normalize_patch` 同一组常数）：实测 51/101/151 也都留得住界行，
但窗口越大墨占比越高（0.164 → 0.213），过大的窗口在大片空白处会把纸纹抬成墨。
956 个真实字框实测：Sauvola31 相对 `<128` 墨量中位 **+5.6%**，683 个框涨、
204 个框跌——是把淡笔画捞回来，不是把笔画打碎。

⚠️ **不要拿它去改 Step1/2 的 `ink_threshold`**：那两步的阈值与一堆几何常数
（`side_floor` 0.045、`GRID_MIN_SCORE` 20…）是一起标定的，换了二值化等于把
那些常数全部作废。这一层只服务「进库 / 人裁 / 展示」，几何链路不动。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

#: 与 `normalize_patch` 共用同一组 Sauvola 常数——两处对同一个字块得到的二值图
#: 应当一致，不该因为「一个在页上做、一个在 64×64 上做」而分叉。
from ..clustering.normalize import SAUVOLA_K, SAUVOLA_WINDOW, sauvola_binarize

BINARIZED_DIRNAME = "binarized"


#: 纸缘 `EDGE_MARGIN` px 内**强制判纸**（2026-09-17）。
#:
#: 扫描件最外一圈是纸张边缘的**浅灰渐变**（bxgb p3 页底实测 185→157）。灰度链路
#: 用固定阈 `<128` 判墨，这一圈全在阈值之上、等于不存在；换成 Sauvola 局部阈，
#: 渐变处「比邻域略暗」就算墨，这一圈整片变黑。
#:
#: 后果是**几何探测被带走**，不是「图不好看」：
#:
#: * 下版框——`find_horizontal_border` 的 `score = proj / 半高宽`，**窄峰分母小**。
#:   纸缘那条伪响应又窄又强（p3: proj 15→661、宽仅 5 → score 5.0→132.2），
#:   反超真框的 66.8。10 页里 **7 页**锁到 y≈2339（真框在 y≈2080）。
#: * 竖界行——右纸缘列墨 0.04→0.41，`find_vertical_lines` 全幅搜索，
#:   p33/p40 的线位偏出 26~30px。
#:
#: 真框自身在两种图上几乎没动（p3 下框 score 69.8→66.8）——坏的只是**多出来的
#: 那个候选**，所以修在「纸缘不参选」，不动 Sauvola 的参数。
#:
#: ⚠️ 试过但无效：在 `binarize_page` 里按「局部方差低就判纸」拦。纸缘是**渐变**
#: 不是平坦区（局部 std 6.6~8.7，与淡笔画同量级），按方差砍要么砍不掉、要么
#: 连淡笔画一起砍。这与 `feedback_sauvola_synthetic_block` 是同一族坑的**另一面**：
#: 那次是均匀实心块内部被判成纸，这次是缓变浅灰被判成墨。
#:
#: 取 20px：bxgb 10 页实测四缘异常深度 上 4 / 下 9 / 左 10 / **右 16**，20 留余量。
#: 版框离纸缘最近也有 250px 以上，这一圈里不可能有正文或版框。
EDGE_MARGIN = 20


def binarize_page(gray: np.ndarray, window: int = SAUVOLA_WINDOW,
                  k: float = SAUVOLA_K,
                  edge_margin: int = EDGE_MARGIN) -> np.ndarray:
    """灰度页 → uint8 {0,255} 的**白底黑字**页图（与原图同尺寸，可直接看）。

    `sauvola_binarize` 返回 {0,1}、1=墨；这里翻成给人看的白底黑字，
    落盘的 PNG 打开就是一张正常的黑白书页。

    **纸缘留白**（`edge_margin`，见上）：最外一圈强制判纸，否则纸张边缘的浅灰
    渐变会被局部阈判成墨，把版框/界行探测带走。
    """
    if gray.ndim == 3:
        import cv2
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    ink = sauvola_binarize(gray.astype(np.uint8), window=window, k=k)
    m = int(edge_margin)
    if m > 0 and ink.shape[0] > 2 * m and ink.shape[1] > 2 * m:
        ink[:m, :] = 0
        ink[-m:, :] = 0
        ink[:, :m] = 0
        ink[:, -m:] = 0
    return np.where(ink > 0, 0, 255).astype(np.uint8)


def binarized_root(repo_root: Path | None = None) -> Path:
    """二值副本的根。与 `precleaned` 同级、同套路——**是产物不是缓存**
    （可重跑、可删掉重来，但不该被 LRU 悄悄清掉，否则人裁看的图会凭空消失）。"""
    from ..core.workspace import workspace_root
    if repo_root:
        return Path(repo_root) / BINARIZED_DIRNAME
    ws = workspace_root()
    base = Path(ws) if ws else Path(__file__).resolve().parents[2]
    return base / BINARIZED_DIRNAME


def binarized_path(book_id: str, page: int, repo_root: Path | None = None) -> Path:
    return binarized_root(repo_root) / book_id / f"{page}.png"


def build_binarized(book, pages=None, *, force: bool = False, window: int = SAUVOLA_WINDOW,
                    k: float = SAUVOLA_K, log: Callable[[str], None] = print,
                    repo_root: Path | None = None) -> list[Path]:
    """给这册书生成整页二值副本，返回写出的文件。

    **读的是 `effective_raw_path`**，不是 `book.raw_path`——登记过 Step0 预清理的页
    要二值化**修好的那张**，否则二值副本里还留着反色带那类坏区（两条链路必须
    读同一张图，见 `preclean.effective_raw_path` 的 docstring）。

    已存在且非 `force` 就跳过。**不碰原图。**
    """
    from cv2 import imread, imwrite
    from .preclean import effective_raw_path

    todo = list(pages) if pages is not None else book.all_pages()
    written: list[Path] = []
    for page in todo:
        dst = binarized_path(book.id, page, repo_root)
        if dst.exists() and not force:
            continue
        src = effective_raw_path(book, page)
        img = imread(str(src), 0)
        if img is None:
            log(f"  p{page} 原图读不出来，跳过: {src}")
            continue
        out = binarize_page(img, window=window, k=k)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not imwrite(str(dst), out):
            raise IOError(f"写盘失败: {dst}")
        written.append(dst)
    log(f"[binarize] {book.id}: 写出 {len(written)} 页 → {binarized_root(repo_root) / book.id}")
    return written


def binarized_or_none(book_id: str, page: int, repo_root: Path | None = None) -> Path | None:
    """这一页的二值副本；没生成就返回 None（调用方退回原图，不报错）。"""
    p = binarized_path(book_id, page, repo_root)
    return p if p.exists() else None
