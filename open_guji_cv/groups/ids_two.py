"""IDS 路的两段版（M7 IDS 扩展，慎愼／參㕘）：一条折线把字块切成两段，只在「有差别的那一段」二选一。

和三段版（`ids_solver`，彝组）同一套思路，只是更简单：
- 参會（上下）：⿱厽X，X ∈ {彡, 小}，切线横向、两端水平延伸；慎愼（左右）：⿰忄X，X ∈ {真, 眞}，切线竖向。
- 切线可以是人标的（评测）或自动缝（`auto_cut`：DP 找穿过墨迹最少的缝，`prior` 是缝的先验位置占图高/宽比例）。
- 决定字的那一段（`which`，缺省 1＝下／右）取归一部件图，在**真实刻例模板**里最近邻，margin 不够弃权。
- 观察到的 IDS 由 `frame.format(部件名)` 拼出（如 `⿱厽{}`），交给 `IdsResolver` 匹配字符：exact／form 给字，其余弃权。
- 只依赖 numpy、PIL（经 `ids_parts`）；不被任何 Step 引用。分层 L2。
"""
from __future__ import annotations

import numpy as np

from .ids import IdsResolver, parse
from .ids_parts import choose, norm_part
from .ids_segment import _interp, ink_of, seam_polyline
from .ids_solver import IdsVerdict


def auto_cut(gray: np.ndarray, orient: str, prior: float, band: float = 0.15, step: int = 8):
    """自动切线（归一化折线）：`orient='h'` 点自左向右，`'v'` 点自上而下。无墨迹返回 None。"""
    ink = ink_of(gray)
    if not ink.any():
        return None
    if orient == "h":
        return seam_polyline(ink, prior, band=band, step=step)
    t = seam_polyline(ink.T, prior, band=band, step=step)          # 转置后横向缝＝原图竖向缝
    return [[y, x] for x, y in t]


def cut_mask(shape: tuple[int, int], polyline, orient: str) -> np.ndarray:
    """折线 → 两类掩码：`h` 0＝上 1＝下；`v` 0＝左 1＝右。折线两端延伸到图边缘。"""
    h, w = shape
    if orient == "h":
        y = _interp(polyline, w) * h
        return ((np.arange(h) + 0.5)[:, None] >= y[None, :]).astype(np.uint8)
    pts = sorted((float(q[1]), float(q[0])) for q in polyline)       # (y, x)
    x = np.interp((np.arange(h) + 0.5) / h, [p[0] for p in pts], [p[1] for p in pts]) * w
    return ((np.arange(w) + 0.5)[None, :] >= x[:, None]).astype(np.uint8)


def part_of(gray: np.ndarray, polyline, orient: str, which: int = 1, sub_prior: float | None = None):
    """切线分出的第 `which` 段，归一部件图（无墨迹返回 None）。

    `sub_prior` 给定时做第二刀：先把该段裁到墨迹外框，再在框内按 `sub_prior`（占框高/宽比例）自动找缝，
    只取缝后的一段（如 參／㕘／叅 的下半＝人＋X，第二刀去掉「人」只留 X）。
    """
    m = cut_mask(gray.shape, polyline, orient)
    part = np.full_like(gray, 255)
    part[m == which] = gray[m == which]
    if sub_prior is not None:
        ink = ink_of(part)
        if not ink.any():
            return None
        ys, xs = np.where(ink)
        sub = part[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        c2 = auto_cut(sub, orient, sub_prior)
        if c2 is None:
            return None
        return part_of(sub, c2, orient, 1)
    return norm_part(part)


def slot_name(resolver: IdsResolver, ch: str, which: int = 1) -> str:
    """字 `ch` 的标准 IDS 里第 `which` 个部件名（如 參 → 彡）。"""
    return str(parse(resolver.canonical[ch]).kids[which])


def add_real(bank: dict, gray: np.ndarray, name: str, polyline, orient: str, which: int = 1,
             sub_prior: float | None = None) -> None:
    """把一个人标过的真实格并进模板库 `{部件名: [模板图,…]}`。"""
    p = part_of(gray, polyline, orient, which, sub_prior)
    if p is not None:
        bank.setdefault(name, []).append(p)


def ids_of_slot(resolver: IdsResolver, name: str, which: int = 1) -> str | None:
    """部件名 → 该部件所在成员的标准 IDS（两字顶层结构不同时没法用统一的 `frame`，如 點 ⿰黑占 ／ 㸃 ⿺黒占）。"""
    for ch, ids in resolver.canonical.items():
        if str(parse(ids).kids[which]) == name:
            return ids
    return None


def _choose_norm(x: np.ndarray, templates: dict, min_margin: float):
    """已归一的部件图 `x` 在模板库里取最近邻（与 `ids_parts.choose` 同分数、同弃权规则）。"""
    from .ids_parts import similarity
    if len(templates) < 2:
        return None, 0.0, {}
    scores = {n: max(similarity(x, t) for t in ts) for n, ts in templates.items() if ts}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    margin = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else ranked[0][1]
    return (ranked[0][0] if margin >= min_margin else None), margin, scores


def solve_two(gray: np.ndarray, bank: dict, resolver: IdsResolver, frame: str | None, orient: str, prior: float,
              polyline=None, which: int = 1, min_margin: float = 0.02, sub_prior: float | None = None) -> IdsVerdict:
    """一格 → 判字。`frame` 如 `⿱厽{}`；顶层结构不同的组给 None，改按 `ids_of_slot` 取标准 IDS。弃权：无墨迹、没有第 `which` 段墨迹、margin 不够、IDS 对不上成员。"""
    if not ink_of(gray).any():
        return IdsVerdict(None, None, "abstain_blank")
    pl = polyline if polyline is not None else auto_cut(gray, orient, prior)
    if pl is None:
        return IdsVerdict(None, None, "abstain_blank")
    m = cut_mask(gray.shape, pl, orient)
    part = np.full_like(gray, 255)
    part[m == which] = gray[m == which]
    if sub_prior is not None:                 # 第二刀：只比最下／最右一小块，bank 里的模板也必须是同样取法
        sub = part_of(gray, pl, orient, which, sub_prior)
        if sub is None:
            return IdsVerdict(None, None, "abstain_slot", slots=(None,), margins=(0.0,))
        part = None
        best, margin, scores = _choose_norm(sub, bank, min_margin)
    else:
        best, margin, scores = choose(part, bank, min_margin=min_margin)
    if best is None:
        return IdsVerdict(None, None, "abstain_slot", slots=(None,), margins=(round(margin, 4),), extra={"scores": scores})
    ids = frame.format(best) if frame else ids_of_slot(resolver, best, which)
    r = resolver.resolve(ids)
    return IdsVerdict(r.char, ids, r.kind, r.flag, (best,), (round(margin, 4),), {"scores": {k: round(v, 4) for k, v in scores.items()}})
