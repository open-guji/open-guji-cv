"""IDS 路的每段二选一（M7 块 C4，GUJI-563）：切好的一段图，在「该位置可选部件」里选哪个。

- 模板：用仓里的自由字体（`fonts/` 里 Jigmo／I.Ming／GenMin，OFL/CC0 等）把成员字渲染出来，
  再按同样的三段切分（直线基线；字体字形干净，直线够用）取每段，得到每个位置每个可选部件的模板；
  实刻例的最近邻（用户标注的 42 格）在 C5 里与它合并，本模块只做字体模板这一路。
- 部件图先裁到墨迹外框、缩到固定大小，再和各候选模板比较：分数＝软 IoU（高斯模糊后的 Dice）。
- `choose` 返回 `(best, margin, scores)`；`margin`（第一名减第二名）不够就弃权（`best=None`），不猜。
- 依赖 numpy、PIL、fontTools；不被任何 Step 引用。分层 L2。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .ids_segment import ink_of, polylines_to_mask, straight_baseline

_ROOT = Path(__file__).resolve().parents[2]
FONT_FILES = (
    "fonts/jigmo/Jigmo.ttf", "fonts/jigmo/Jigmo2.ttf", "fonts/iming/I.Ming-8.10.ttf",
    "fonts/genmin/GenRyuMin2TC-R.otf",
)
PART_SIZE = 32


@lru_cache(maxsize=None)
def _cmap(path: str) -> frozenset:
    from fontTools.ttLib import TTFont
    return frozenset(TTFont(path, lazy=True).getBestCmap())


def fonts_for(ch: str) -> list[str]:
    """含有 `ch` 的字体文件（按 FONT_FILES 顺序）。"""
    out = []
    for f in FONT_FILES:
        p = _ROOT / f
        if p.exists() and ord(ch) in _cmap(str(p)):
            out.append(str(p))
    return out


def render(ch: str, font_path: str, size: int = 128) -> np.ndarray:
    """把单字渲染成灰度图（深墨浅底），居中，留边。"""
    font = ImageFont.truetype(font_path, int(size * 0.86))
    img = Image.new("L", (size, size), 255)
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), ch, font=font)
    d.text(((size - (r - l)) / 2 - l, (size - (b - t)) / 2 - t), ch, fill=0, font=font)
    return np.asarray(img)


def norm_part(part_gray: np.ndarray, size: int = PART_SIZE) -> np.ndarray | None:
    """部件图 → 裁墨迹外框 → 缩成 size×size 的 0–1 墨迹图（无墨迹返回 None）。"""
    ink = ink_of(part_gray)
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    crop = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255
    im = Image.fromarray(crop).resize((size, size), Image.BILINEAR)
    return np.asarray(im, dtype=np.float32) / 255.0


def _blur(a: np.ndarray) -> np.ndarray:
    k = np.array([1, 4, 6, 4, 1], dtype=np.float32) / 16
    a = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, a)
    return np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 1, a)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """模糊后的 Dice：越大越像。"""
    a, b = _blur(a), _blur(b)
    den = float(a.sum() + b.sum())
    return 0.0 if den == 0 else float(2 * np.minimum(a, b).sum() / den)


def font_parts(ch: str, font_path: str) -> list[np.ndarray | None]:
    """一个字在一种字体里的三段（直线基线切）→ 归一部件图。"""
    g = render(ch, font_path)
    y1, y2 = straight_baseline(ink_of(g), smooth=5)
    mask = polylines_to_mask(g.shape, [[0, y1], [1, y1]], [[0, y2], [1, y2]])
    out = []
    for k in range(3):
        part = np.full_like(g, 255); part[mask == k] = g[mask == k]
        out.append(norm_part(part))
    return out


def build_bank(slot_of_char: dict) -> dict:
    """`slot_of_char = {字: (上部件名, 中部件名, 下部件名)}` → `{位置: {部件名: [模板图,…]}}`（每种字体一张）。"""
    bank: dict = {0: {}, 1: {}, 2: {}}
    for ch, names in slot_of_char.items():
        for fp in fonts_for(ch):
            for k, img in enumerate(font_parts(ch, fp)):
                if img is not None:
                    bank[k].setdefault(names[k], []).append(img)
    return bank


def choose(part_gray: np.ndarray, templates: dict, min_margin: float = 0.0):
    """在 `{部件名: [模板图,…]}` 里选最像的。返回 `(best|None, margin, {名: 分数})`。"""
    x = norm_part(part_gray)
    if x is None or len(templates) < 2:
        return None, 0.0, {}
    scores = {n: max(similarity(x, t) for t in ts) for n, ts in templates.items() if ts}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    margin = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else ranked[0][1]
    return (ranked[0][0] if margin >= min_margin else None), margin, scores
