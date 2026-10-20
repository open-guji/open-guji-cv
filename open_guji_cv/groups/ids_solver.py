"""IDS 路定字（M7 块 C5，GUJI-563）：切分 → 每段二选一 → 拼出观察到的 IDS → `IdsResolver` 匹配字符。

流程（用户 10-17：先认最准确的 IDS，再匹配字符）：
1. 切分：给定折线（评测时用人标的）或 `auto`（直线基线，U-Net 切分器接入前的占位）；
2. 每个位置在该组可选部件里选一个（`ids_parts.choose`，margin 不够就弃权）；
3. 三段都选出来才拼 IDS（`⿳上⿰米X下` 的写法由 `slots_to_ids` 统一生成），再交给 `IdsResolver`：
   exact／form → 给字；nearest → 给字并带 `nearest_variant` 旗；none → 弃权。
任何一段弃权整格弃权，不猜。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .ids import IdsResolver, parse
from .ids_parts import choose, choose_hog
from .ids_segment import ink_of, polylines_to_mask, right_part, split_parts, straight_baseline, vertical_seam


@dataclass
class IdsVerdict:
    char: str | None
    ids: str | None
    kind: str                       # exact | form | nearest | none | abstain_slot | abstain_blank
    flag: str | None = None
    slots: tuple = (None, None, None)
    margins: tuple = (0.0, 0.0, 0.0)
    extra: dict = field(default_factory=dict)


def slots_to_ids(top: str, mid: str, bot: str) -> str:
    """三个位置的部件名 → 压平后的 IDS 串。中段名形如 `米糸`／`米分`，写成 `⿰米X`。"""
    mid_ids = mid if mid.startswith("⿰") else "⿰" + mid
    return f"⿳{top}{mid_ids}{bot}"


def _mid_name(rname: str) -> str:
    return rname if rname.startswith("米") else "米" + rname


def solve(gray: np.ndarray, bank: dict, resolver: IdsResolver, polylines=None, min_margin: float = 0.05, vcut=None,
          mid_hog: float | None = None) -> IdsVerdict:
    """`bank = ids_parts.build_bank(...)`（位置 → 部件名 → 模板）；`polylines=(上/中, 中/下)` 缺省用直线基线。
    库里有 `bank[3]`（中段右半 糸／分）时，中段改认「竖切后的右半」：`vcut` 缺省用 `vertical_seam` 自动切。
    `mid_hog` 给了数：中段改用 HOG＋岭回归判别（`choose_hog`），判别值绝对值不到它就弃权；上下段仍用软 IoU 近邻。"""
    ink = ink_of(gray)
    if not ink.any():
        return IdsVerdict(None, None, "abstain_blank")
    if polylines is None:
        y1, y2 = straight_baseline(ink, smooth=3)
        polylines = ([[0, y1], [1, y1]], [[0, y2], [1, y2]])
    mask = polylines_to_mask(gray.shape, polylines[0], polylines[1])
    parts = split_parts(gray, mask)
    picks, margins = [], []
    for k in range(3):
        if k == 1 and bank.get(3):
            vc = vcut if vcut is not None else vertical_seam(ink, mask)
            if vc is None:
                picks.append(None); margins.append(0.0); continue
            rp = right_part(gray, mask, vc)
            best, m, _ = (choose_hog(rp, bank[3], min_margin=mid_hog) if mid_hog is not None
                          else choose(rp, bank[3], min_margin=min_margin))
            picks.append(_mid_name(best) if best else None); margins.append(round(m, 4))
            continue
        best, m, _ = choose(parts[k], bank[k], min_margin=min_margin)
        picks.append(best); margins.append(round(m, 4))
    if any(p is None for p in picks):
        return IdsVerdict(None, None, "abstain_slot", slots=tuple(picks), margins=tuple(margins))
    ids = slots_to_ids(*picks)
    r = resolver.resolve(ids)
    return IdsVerdict(r.char, ids, r.kind, r.flag, tuple(picks), tuple(margins))


def parts_of(gray: np.ndarray, polylines=None):
    """一格 → 三段归一部件图（`norm_part`）；无墨迹返回 None。切法同 `solve`。"""
    from .ids_parts import norm_part
    ink = ink_of(gray)
    if not ink.any():
        return None
    if polylines is None:
        y1, y2 = straight_baseline(ink, smooth=3)
        polylines = ([[0, y1], [1, y1]], [[0, y2], [1, y2]])
    mask = polylines_to_mask(gray.shape, polylines[0], polylines[1])
    return [norm_part(p) for p in split_parts(gray, mask)]


def add_real(bank: dict, gray: np.ndarray, names: tuple, polylines=None, vcut=None) -> None:
    """把一个人标过的真实格（三段名 `names`）并进模板库。真实字形比字体渲染近得多（见 research/m7/eval_c5.py）。"""
    ps = parts_of(gray, polylines)
    for k, p in enumerate(ps or ()):
        if p is not None:
            bank[k].setdefault(names[k], []).append(p)
    if vcut is not None and polylines is not None:
        from .ids_parts import norm_part
        mask = polylines_to_mask(gray.shape, polylines[0], polylines[1])
        r = norm_part(right_part(gray, mask, vcut))
        if r is not None:
            bank.setdefault(3, {}).setdefault(names[1][1:] if names[1].startswith("米") else names[1], []).append(r)
