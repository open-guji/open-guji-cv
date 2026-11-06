"""异体边表自动暂归一：从关系层（`variants.py` 的边＋来源分级）自动认「同词异形」的字对，替代逐对登记 `follow_ref`。

背景（A24 2026-10-31，r5 重放 V 类「组外异体对」单格长尾约 360 对）：这些对每对只有 1 格，建不了字形判法，也等不到
逐对 sheldon 点头；但其中一部分字典证据很硬（≥2 家异体字典收、`edge_tier` 判 T1 纯异体）。第 6 路「库首位
与整理本互为异体对」原先一律送审（`lane_variant_guard`），这里给它一条通则：

    自动对 = 边表 T1（纯异体，非互通／一对多／简繁）且 ≥2 个异体来源（或有本书刻例边 `local:keben`）
             且两字都不在任何字组里（字组自己判）且不在 `config/variants/edge_pair_exclude.tsv`

只用在**库首位 cov 够、与整理本互为自动对**的待审格上（判据同 `seed_admit.follow_ref_decide`），放 `pair_to(a, b)`：
两形里已放行字频更高的一形（`config/variants/form_freq.tsv`），两形都罕见（<`FREQ_MIN`）时放库首位。
这是**同义异体暂归一**（sheldon 2026-10-25／10-27 定，只限同义），证据记 `decision: provisional`、通道 `edge_pair`，
将来按这个标记筛出来再按刻形拆。意思不同的形近字（不是 T1、或在排除表里）一律不碰。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "config" / "variants"
#: 两形里较常见的一形至少放行这么多格才算「有常见形」；否则放库首位（库的刻形证据）。
FREQ_MIN = 20
#: 至少几个异体来源（`variants.BRIDGE_SOURCES` 里的）才自动认。
MIN_SOURCES = 2


@lru_cache(maxsize=1)
def _exclude() -> frozenset:
    out = set()
    p = _DIR / "edge_pair_exclude.tsv"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            f = line.split("\t")
            if len(f) >= 2 and len(f[0]) == 1 and len(f[1]) == 1:
                out.add(frozenset((f[0], f[1])))
    return frozenset(out)


@lru_cache(maxsize=1)
def _freq() -> dict:
    out: dict[str, int] = {}
    p = _DIR / "form_freq.tsv"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            ch, _, n = line.partition("\t")
            if n.strip().isdigit():
                out[ch] = int(n)
    return out


@lru_cache(maxsize=1)
def _group_chars() -> frozenset:
    from .registry import FLOW_GROUPS
    return frozenset(c for g in FLOW_GROUPS.values() for c in g.members)


@lru_cache(maxsize=1)
def _graph():
    from .. import variants
    return variants._graph()


@lru_cache(maxsize=65536)
def is_auto_pair(a: str, b: str) -> bool:
    """a、b 是否算自动暂归一的同词异形对（无向）。"""
    if not a or not b or a == b or len(a) != 1 or len(b) != 1:
        return False
    if a in _group_chars() or b in _group_chars() or frozenset((a, b)) in _exclude():
        return False
    e = _graph().variant_edge(a, b)
    if e.tier != "T1":
        return False
    return e.n_bridge >= MIN_SOURCES or "local:keben" in e.sources


@lru_cache(maxsize=1)
def _group_kinds() -> dict:
    """字 → 它所在字组的 kind 集合（variant／near_form…）。"""
    from .registry import FLOW_GROUPS
    out: dict[str, set] = {}
    for g in FLOW_GROUPS.values():
        for c in g.members:
            out.setdefault(c, set()).add(getattr(g, "kind", None) or "")
    return {k: frozenset(v) for k, v in out.items()}


@lru_cache(maxsize=65536)
def seam_pair(a: str, b: str) -> str | None:
    """字组缝（A24 V01 深挖 11-06，第 7 轮）：a、b 是纯异体强边（T1、≥2 来源或本书刻例边）、不在排除表，
    但至少一字是字组成员，所以 `is_auto_pair` 不认；而这一格字组入口又没接（库分差内有组外字、或另一形不是组员）。
    → 涉及的字组里只要有形近组就返回 ``"near_form"``（调用方要更大的领先），否则 ``"variant"``；不是这种对返回 None。"""
    if not a or not b or a == b or len(a) != 1 or len(b) != 1 or frozenset((a, b)) in _exclude():
        return None
    kinds = _group_kinds().get(a, frozenset()) | _group_kinds().get(b, frozenset())
    if not kinds:
        return None                     # 两字都不在字组：归 is_auto_pair 管
    e = _graph().variant_edge(a, b)
    if e.tier != "T1" or not (e.n_bridge >= MIN_SOURCES or "local:keben" in e.sources):
        return None
    return "variant" if kinds <= {"variant"} else "near_form"


def pair_to(a: str, b: str, *, lib_top: str | None = None) -> str:
    """暂归一放哪一形：已放行字频较高的一形；都罕见（<FREQ_MIN）时放 `lib_top`（缺省 a）。"""
    f = _freq()
    fa, fb = f.get(a, 0), f.get(b, 0)
    if max(fa, fb) < FREQ_MIN:
        return lib_top if lib_top in (a, b) else a
    return a if fa >= fb else b
