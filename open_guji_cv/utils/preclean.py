"""Step0 预清理：把扫描件上的坏区修好，产物落盘，Step1 起自动读修好的那张。

**默认整本书什么都不做。** 只有在 books/<book>.yaml 里 `preclean:` 段登记过的页才处理 ——
坏页是人工确认的，位置也是人工（或 scripts/scan_inverted_bands.py 辅助）定的，
当作参数写进 yaml，不猜。

三件事分开
---------
1. **磁盘原图永不改写**（raw_dir 里那张是唯一真相）；
2. 修好的图落在 `precleaned/<book>/<page>.png`，由 `python -m open_guji_cv.cli_v2 preclean`
   显式生成 —— 这是个可重跑、可删掉重来的产物，不是缓存（不会被 LRU 清掉）；
3. `RunContext.raw_page` 优先读 precleaned 里那张；没有就读原图。
   所以 Step1 及其下游一行代码都不用改，未登记的页也完全不受影响。

目前只有一种坏区：`inverted_band`
--------------------------------
一条横带内**黑白是反的**（纸成黑、字成白）。不是墨污 —— 是扫描/二值化在这一带翻了极性，
所以修法是把带内的点整体反回来，字迹一笔不少地还原（抹除法会连笔画一起抹掉，是有损的）。

带的边界是**多段梯形**：上沿一级级抬高，下沿基本平，中间可能断开。所以不能用一对固定的 y，
得逐列量。量的办法是找**列间纸列** —— 上下文都无墨、本该全白的那些列；带内它们是纯黑的
一段，且黑得干净（没有笔画混进来），一量一个准。量到的点中值滤波去异常，再线性内插到整段。

实测（vol02 p151，原图 2307×3049）：
  反色前带内墨占比 0.806（纸被翻成黑）→ 反色后 0.194，正文正常水平 0.152，对上了。
  逐字核对整理本「真卿所見者四卷全本…傳寫者諱其殘缺因於書名增入卦爻二字」，
  所見 / 者 / 缺因 笔画完整。p152 同理，对上「周易要義十卷…宋魏了翁撰…僉書樞密院事」。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter

# 修好的图落在这里。是产物不是缓存：显式生成、可删掉重来、不会被 LRU 清掉。
PRECLEANED_DIRNAME = "precleaned"


def _trace_band(b: np.ndarray, y_lo: int, y_hi: int, y_probe: int,
                ctx: int, smooth: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """用列间纸列量出带的上下沿。返回 (量到的 x, 上沿, 下沿)。

    列间纸列 = 带上方 ctx 行与带下方 ctx 行都无墨的列。带内这些列是纯黑的一段，
    取包含 y_probe 的那段连续黑，就是带在该列的上下沿。
    """
    above = b[y_lo - ctx:y_lo].any(axis=0)
    below = b[y_hi:y_hi + ctx].any(axis=0)
    paper = ~above & ~below

    w = b.shape[1]
    top = np.full(w, -1, int)
    bot = np.full(w, -1, int)
    for x in np.flatnonzero(paper):
        col = b[y_lo:y_hi, x].astype(np.uint8)
        idx = np.flatnonzero(np.diff(np.r_[0, col, 0]))
        for a, c in zip(idx[::2], idx[1::2]):
            if y_lo + a <= y_probe <= y_lo + c - 1:
                top[x] = y_lo + a
                bot[x] = y_lo + c - 1
                break
    xs = np.flatnonzero(top >= 0)
    if xs.size == 0:
        raise ValueError("没量到带：检查 y_lo/y_hi/y_probe 是否框住了污渍带")
    t = median_filter(top[xs].astype(float), size=smooth, mode="nearest")
    bo = median_filter(bot[xs].astype(float), size=smooth, mode="nearest")
    return xs, t, bo


def invert_band(gray: np.ndarray, *, segments: list[list[int]],
                y_lo: int, y_hi: int, y_probe: int,
                ink_threshold: int = 128, ctx: int = 170,
                smooth: int = 31) -> np.ndarray:
    """把多段梯形围出的区域整体黑白反转，返回新图；入参不改。

    segments  横向分段 [[x0, x1], ...]，闭区间；带中间断开的地方要分开写。
    y_lo/y_hi 搜索窗（带一定落在窗内），y_probe 窗内一定在带里的一行。
    ctx       量列间纸列时，往带上下各看多少行。
    """
    b = gray < ink_threshold
    xs, t, bo = _trace_band(b, y_lo, y_hi, y_probe, ctx, smooth)

    mask = np.zeros(gray.shape, bool)
    for x0, x1 in segments:
        gx = np.arange(x0, x1 + 1)
        tt = np.round(np.interp(gx, xs, t)).astype(int)
        bb = np.round(np.interp(gx, xs, bo)).astype(int)
        for x, a, c in zip(gx, tt, bb):
            mask[a:c + 1, x] = True

    out = gray.copy()
    out[mask] = 255 - gray[mask]
    return out


_OPS = {"inverted_band": invert_band}


def apply_preclean(gray: np.ndarray, rules: list[dict]) -> tuple[np.ndarray, list[str]]:
    """按 book.yaml 里登记的规则依次处理一页。返回 (新图, 每条规则的说明)。"""
    notes: list[str] = []
    out = gray
    for r in rules:
        kind = r.get("kind", "inverted_band")
        fn = _OPS.get(kind)
        if fn is None:
            raise ValueError(f"未知的 preclean 类型: {kind}（可用: {sorted(_OPS)}）")
        kw = {k: v for k, v in r.items() if k not in ("kind", "page", "note")}
        th = kw.get("ink_threshold", 128)
        before = float((out < th).mean())
        out = fn(out, **kw)
        after = float((out < th).mean())
        notes.append(f"{kind}: 全页墨占比 {before:.3f} -> {after:.3f}")
    return out, notes


# ── 产物落盘 ────────────────────────────────────────────────────────
def precleaned_root(repo_root: Path | None = None) -> Path:
    base = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    return base / PRECLEANED_DIRNAME


def precleaned_path(book_id: str, page: int, repo_root: Path | None = None) -> Path:
    return precleaned_root(repo_root) / book_id / f"{page}.png"


def build_precleaned(book, pages=None, *, force: bool = False,
                     log=print, repo_root: Path | None = None) -> list[Path]:
    """按 book.preclean 生成修好的页图，返回写出的文件。

    只处理登记过的页；已存在且非 force 就跳过。**不碰 raw_dir 里的原图。**
    """
    from cv2 import imread, imwrite

    rules_by_page = getattr(book, "preclean", {}) or {}
    todo = sorted(rules_by_page) if pages is None else [p for p in pages if p in rules_by_page]
    if pages is not None:
        missing = [p for p in pages if p not in rules_by_page]
        if missing:
            log(f"这些页没在 {book.id}.yaml 的 preclean 段里登记，跳过: {missing}")

    written: list[Path] = []
    for page in todo:
        dst = precleaned_path(book.id, page, repo_root)
        if dst.exists() and not force:
            log(f"  p{page} 已有，跳过（--force 可重做）: {dst}")
            continue
        src = book.raw_path(page)
        img = imread(str(src), 0)
        if img is None:
            raise FileNotFoundError(f"原图缺失: {src}")
        out, notes = apply_preclean(img, rules_by_page[page])
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not imwrite(str(dst), out):
            raise IOError(f"写盘失败: {dst}")
        for n in notes:
            log(f"  p{page} {n}")
        log(f"  p{page} -> {dst}")
        written.append(dst)
    return written
