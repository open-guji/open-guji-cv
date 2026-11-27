"""`_shape_first_ok`：形近字线交上下文的对 tier 记成字符串 "context"，不是终判档，不当证据也不许让整页 TypeError
（全唐文 004 p162 奥奧，decide-bench 动态层 11-26）。"""
from types import SimpleNamespace

from open_guji_cv.steps import seed_admit_common as C


def _p():
    return SimpleNamespace(lane_shape_first="x", lane_shape_first_fingerprint="")


def test_tier_context_string_does_not_raise(monkeypatch):
    monkeypatch.setattr(C, "_shape_variant_pairs", lambda *_a, **_k: frozenset({frozenset("奥奧")}))
    rows = [{"cand": "奥", "pair": "奥奧", "rank": 1, "tier": "context", "lean": "奥"}]
    m = SimpleNamespace(stage={"pair": rows})
    assert C._shape_first_ok(_p(), m, "奥", "奧", "奥") is False


def test_tier_3_int_still_counts(monkeypatch):
    monkeypatch.setattr(C, "_shape_variant_pairs", lambda *_a, **_k: frozenset({frozenset("奥奧")}))
    rows = [{"pair": "奥奧", "tier": 3, "lean": "奥"}]
    m = SimpleNamespace(stage={"pair": rows})
    assert C._shape_first_ok(_p(), m, "奥", "奧", "奥") is True
