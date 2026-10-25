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


def _run(monkeypatch, cur, pick, abstain=True, channel="match_ref", provenance="match_ref", evidence=None, book_cp=None):
    monkeypatch.setattr(sa, "_shadow_gate", lambda p: _Gate(pick))
    monkeypatch.setattr(sa, "_opt", lambda ctx, kind, page: None)
    import open_guji_cv.clustering.variants as variants
    monkeypatch.setattr(variants.VariantMap, "load", classmethod(lambda cls, *a, **k: _VMap()))
    rec = AdmitRec(id="v:1:1:1", slot=1, sub=None, admit=True, channel=channel, char=cur,
                   provenance=provenance, doubts=[], evidence=evidence or {})
    out = [SimpleNamespace(chars=[rec])]
    m = SimpleNamespace(candidates=[(cur, 0.97)], guard=None, verdict="same", cov=0.97, wmax=0.0)
    p = sa.SeedAdmitParams(shadow_veto=True, shadow_veto_variant_abstain=abstain)
    book = SimpleNamespace(codepoints=book_cp or {}, canonical_char=lambda c: (book_cp or {}).get(c, c))
    n = sa._shadow_veto_pass(SimpleNamespace(book=book), 1, p, out, {rec.id: m}, {})
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


def test_group_context_pick_in_same_group_is_kept(monkeypatch):
    """字组按文意定的字（group_flow＋context），影子挑同组另一个字 → 不降；挑组外字、或不是按文意定的照常降。"""
    ev = {"group": {"id": "ry", "decision": "fix"}}
    n, rec = _run(monkeypatch, cur="曰", pick="日", channel="group_flow", provenance="context", evidence=ev)
    assert n == 0 and rec.admit
    n, rec = _run(monkeypatch, cur="曰", pick="田", channel="group_flow", provenance="context", evidence=ev)
    assert n == 1 and not rec.admit
    n, rec = _run(monkeypatch, cur="曰", pick="日", channel="group_flow", provenance="match", evidence=ev)
    assert n == 1 and not rec.admit


def test_book_codepoints_pick_abstains(monkeypatch):
    """册 `codepoints:` 归一后同字（晩→晚）：影子挑了另一个码位不算认错；没配该对则照常降。"""
    n, rec = _run(monkeypatch, cur="晚", pick="晩", abstain=False, book_cp={"晩": "晚"})
    assert n == 0 and rec.admit
    n, rec = _run(monkeypatch, cur="晚", pick="晩", abstain=False, book_cp={})
    assert n == 1 and not rec.admit


def test_variant_group_decided_codepoint_is_kept(monkeypatch):
    """同义字组（can 參㕘叅）流程已按刻形给了放行字：影子挑同组另一个码位 → 不降；组没同意、挑组外字、形近组照常降。"""
    ev = {"group": {"id": "can", "decision": "keep", "why": "agree", "pick": "㕘"}}
    n, rec = _run(monkeypatch, cur="㕘", pick="叅", abstain=False, evidence=ev)
    assert n == 0 and rec.admit
    n, rec = _run(monkeypatch, cur="㕘", pick="叅", abstain=False,
                  evidence={"group": {"id": "can", "decision": "keep", "why": "abstain", "pick": None}})
    assert n == 1 and not rec.admit
    n, rec = _run(monkeypatch, cur="㕘", pick="參", abstain=False,
                  evidence={"group": {"id": "can", "decision": "keep", "why": "agree", "pick": "參"}})
    assert n == 1 and not rec.admit
    n, rec = _run(monkeypatch, cur="㕘", pick="衆", abstain=False, evidence=ev)
    assert n == 1 and not rec.admit
    n, rec = _run(monkeypatch, cur="曰", pick="日", abstain=False,
                  evidence={"group": {"id": "ry", "decision": "keep", "why": "agree", "pick": "曰"}})
    assert n == 1 and not rec.admit


def test_near_form_group_glyph_lift_is_kept(monkeypatch):
    """形近组补放、整字 HOG 给了放行字：影子挑同组另一个字 → 不降（vol16:42:4:3 傳）；只有文意表弃权没有字形票、或挑组外字照常降。"""
    sol = [{"solver": "ctx", "char": None}, {"solver": "ids", "char": "傳", "margin": 1.53}]
    ev = {"group": {"id": "fc", "decision": "admit", "why": "agree", "pick": "傳", "solvers": sol}}
    n, rec = _run(monkeypatch, cur="傳", pick="傅", abstain=False, channel="group_flow", provenance="match", evidence=ev)
    assert n == 0 and rec.admit
    n, rec = _run(monkeypatch, cur="傳", pick="傅", abstain=False, channel="group_flow", provenance="match",
                  evidence={"group": {**ev["group"], "solvers": sol[:1]}})
    assert n == 1 and not rec.admit
    n, rec = _run(monkeypatch, cur="傳", pick="傷", abstain=False, channel="group_flow", provenance="match", evidence=ev)
    assert n == 1 and not rec.admit
