# -*- coding: utf-8 -*-
"""overview#431：影子选的字与现放行字是异体同字时，影子弃权、不降级。"""
from __future__ import annotations

from types import SimpleNamespace

from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.shadow.gate import ShadowVerdict
from open_guji_cv.steps import seed_admit as sa


class _Gate:
    model, conf, low_conf = SimpleNamespace(version="m", meta={}), 0.8, 0.0

    def __init__(self, pick):
        self.pick = pick

    def judge(self, ev):
        return ShadowVerdict(True, "differs", self.pick, 0.9, 0.02)


class _VMap:
    _sem = {"㫖": "旨", "旨": "旨", "旣": "既", "既": "既", "曰": "曰", "日": "日"}

    def semantic(self, c):
        return self._sem.get(c, c)


def _run(monkeypatch, cur, pick, abstain=True):
    monkeypatch.setattr(sa, "_shadow_gate", lambda p: _Gate(pick))
    monkeypatch.setattr(sa, "_opt", lambda ctx, kind, page: None)
    import open_guji_cv.clustering.variants as variants
    monkeypatch.setattr(variants.VariantMap, "load", classmethod(lambda cls, *a, **k: _VMap()))
    rec = AdmitRec(id="v:1:1:1", slot=1, sub=None, admit=True, channel="match_ref", char=cur,
                   provenance="match_ref", doubts=[], evidence={})
    out = [SimpleNamespace(chars=[rec])]
    m = SimpleNamespace(candidates=[(cur, 0.97)], guard=None, verdict="same", cov=0.97, wmax=0.0)
    p = sa.SeedAdmitParams(shadow_veto=True, shadow_veto_variant_abstain=abstain)
    n = sa._shadow_veto_pass(None, 1, p, out, {rec.id: m}, {})
    return n, rec


def test_variant_pick_abstains(monkeypatch):
    n, rec = _run(monkeypatch, cur="旣", pick="既")
    assert n == 0 and rec.admit and "shadow_veto" not in rec.doubts


def test_different_char_still_vetoes(monkeypatch):
    n, rec = _run(monkeypatch, cur="曰", pick="日")
    assert n == 1 and not rec.admit and "shadow_veto" in rec.doubts


def test_switch_off_restores_old_behaviour(monkeypatch):
    n, rec = _run(monkeypatch, cur="㫖", pick="旨", abstain=False)
    assert n == 1 and not rec.admit


def test_rare_codepoint_cur_does_not_abstain(monkeypatch):
    """#431：放行字是罕用码位（𠮓，扩展区）时不弃权，照常降级。"""
    _VMap._sem.update({"𠮓": "變", "變": "變"})
    n, rec = _run(monkeypatch, cur="𠮓", pick="變")
    assert n == 1 and not rec.admit
