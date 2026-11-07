"""坐标对位里的缅甸字母占位（整理本以图代字）当〓看，机器字不取占位符（A24 R01，史記 3 格）。"""
from types import SimpleNamespace

from open_guji_cv.steps import seed_admit as sa


def test_placeholder_norm():
    assert sa._ref_placeholder_norm("ခ") == "〓"
    assert sa._ref_placeholder_norm("ခ") == "〓"
    assert sa._ref_placeholder_norm("卿") == "卿"
    assert sa._ref_placeholder_norm("") == ""
    assert sa._ref_placeholder_norm(None) is None


def test_coord_refs_maps_placeholder(monkeypatch):
    page = SimpleNamespace(coord=[SimpleNamespace(id="a", ref_char="ခ"),
                                  SimpleNamespace(id="b", ref_char="史"),
                                  SimpleNamespace(id="c", ref_char="")])
    monkeypatch.setattr(sa, "_opt", lambda ctx, step, p: page)
    assert sa._coord_refs(None, 1, {}) == {"a": "〓", "b": "史", "c": ""}


def test_context_guard_ignores_placeholder(monkeypatch):
    p = SimpleNamespace(context_guard_diff=False, context_guard_ref_blank=True,
                        context_guard_ref_prefer=True, context_guard_cov=0.9)
    r = SimpleNamespace(id="a", verdict="unsure", cov=0.91)
    vmap = SimpleNamespace(semantic=lambda c: c)
    page = SimpleNamespace(coord=[SimpleNamespace(id="a", ref_char="ခ")])
    monkeypatch.setattr(sa, "_opt", lambda ctx, step, pg: page)
    coord = sa._coord_refs(None, 1, {})
    assert sa._context_guard(p, r, "史", coord, vmap) is None
