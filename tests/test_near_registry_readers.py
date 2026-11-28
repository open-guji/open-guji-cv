"""形近字组登记表第二期（W1，2026-11-28）：改读登记表的读口，派生结果与旧来源**逐项相等**。

`confusable.NEVER_MATCH_FAMILIES`、`confusable.partners()` 原先直接读三张来源表（手工字面量、人裁表、字体表），现在从
`config/near_groups/v2.json` 按字对的 `src` 派生；跟着走的 `match._PARTNER`（护栏 1）、`seeding.NEAR_FORM_CHARS`（near_form 疑问）、
`seed_admit` 里三处 `partners()`、`shadow/signals.py` 源码一字没改，取值经这里逐项比过。这几样都不比个数，比整个集合／映射。

「旧来源」：手工表按 2026-11-28 搬家前 `confusable.py` 的字面量冻结在下面（`OLD_HAND`），人裁表与字体表照旧读 `config/` 下的原表，
`_old_partners` 是搬家前 `partners()` 的原样实现。只读仓里的表，不读活数据。
"""
from __future__ import annotations

import hashlib
import json

import pytest

from open_guji_cv.clustering import confusable as C

# 2026-11-28 搬家前 open_guji_cv/clustering/confusable.py 的 NEVER_MATCH_FAMILIES 字面量（顺序、方向原样）
OLD_HAND: list[tuple[str, str]] = [
    ("諭", "論"), ("遺", "還"), ("圓", "圖"), ("大", "太"), ("廣", "贋"),
    ("候", "侯"), ("間", "問"), ("已", "巳"), ("曾", "會"), ("選", "過"),
    ("人", "入"), ("未", "末"), ("面", "而"), ("夬", "夫"), ("彖", "象"),
    ("匕", "七"), ("日", "曰"), ("揀", "棟"), ("己", "已"), ("己", "巳"),
]


def _unordered(pairs) -> set[tuple[str, str]]:
    return {(a, b) if a <= b else (b, a) for a, b in pairs}


def _old_partners(tau, path, env: str) -> dict[str, frozenset[str]]:
    """搬家前 `confusable.partners()` 的原样实现（手工表换成冻结的字面量）。"""
    human = True
    if env == "off":
        tau, human = None, False
    elif env in ("hand+human", "nofont"):
        tau = None
    elif env:
        tau = float(env)
    acc: dict[str, set[str]] = {}
    pairs = set(OLD_HAND) | (set(C._flat(C.HUMAN_TABLE)) if human else set())
    if tau is not None:
        pairs |= set(C.font_pairs(tau, path))
    for a, b in pairs:
        acc.setdefault(a, set()).add(b)
        acc.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in acc.items()}


def test_hand_source_moved_verbatim():
    """手工表真源搬进 config/near_groups/hand.json：顺序、方向与原字面量一字不差。"""
    assert C.hand_pairs() == OLD_HAND


def test_never_match_families_equals_old():
    got = C.NEVER_MATCH_FAMILIES
    assert len(got) == len(set(got)) == len(OLD_HAND)
    assert set(got) == _unordered(OLD_HAND)
    from open_guji_cv.clustering import match
    assert match.NEVER_MATCH_FAMILIES is got          # 再导出的还是同一个


def test_near_form_chars_equals_old():
    from open_guji_cv.clustering.seeding import NEAR_FORM_CHARS
    assert NEAR_FORM_CHARS == frozenset(c for p in OLD_HAND for c in p)


def test_manager_never_match_hash_unchanged():
    """guji-manager `ops/corpus_pack._never_match_hash`（底库清单的 code_tables）与顺序、方向无关：新旧同值。"""
    def h(fams):
        items = sorted("".join(sorted(map(str, f))) for f in fams)
        return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode()).hexdigest()
    assert h(C.NEVER_MATCH_FAMILIES) == h(OLD_HAND)


@pytest.mark.parametrize("env", ["", "off", "hand+human", "nofont", "0.988", "0.99", "0.98"])
@pytest.mark.parametrize("tau", [C.FONT_TAU, None, 0.99, 0.95])
def test_partners_equals_old(monkeypatch, env, tau):
    """`partners()` 在各种 τ 与 `GUJI_CONFUSABLE` 取值下与旧实现逐字逐对手相等。"""
    monkeypatch.setattr(C, "_ENV", env)
    C.partners.cache_clear()
    try:
        assert C.partners(tau) == _old_partners(tau, None, env)
    finally:
        C.partners.cache_clear()


def test_partners_default_and_guard_map_equal_old():
    """缺省调用（`match._PARTNER`、seed_admit 三处、shadow/signals 都这么调）与旧实现相等；按现进程的 `GUJI_CONFUSABLE`。"""
    old = _old_partners(C.FONT_TAU, None, C._ENV)
    assert C.partners() == old
    from open_guji_cv.clustering import match
    assert match._PARTNER == old


def test_partners_other_font_table_reads_file(tmp_path):
    """给了别的字体表（`path`）照旧读那张表，不拿登记表里的字体对顶替。"""
    p = tmp_path / "font.json"
    p.write_text(json.dumps({"pairs": {"甲由": 0.999}}, ensure_ascii=False), encoding="utf-8")
    if C._ENV in ("off", "hand+human", "nofont"):
        pytest.skip("GUJI_CONFUSABLE 关了字体表")
    got = C.partners(C.FONT_TAU, str(p))
    assert got == _old_partners(C.FONT_TAU, str(p), C._ENV)
    assert got["甲"] == {"由"}


def test_registry_sources_cover_old_tables():
    """登记表里三种 src 的对与三张原表（字体表取 τ≥FONT_TAU）逐对相等——派生的前提；剔除名单哪天剔了字体对就在这里红。"""
    assert set(C.registry_pairs("hand")) == _unordered(OLD_HAND)
    assert set(C.registry_pairs("human")) == set(C._flat(C.HUMAN_TABLE))
    assert set(C.registry_pairs("font")) == set(C.font_pairs(C.FONT_TAU))
