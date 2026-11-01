"""字块图像＋文意 L4（`groups/vis_llm`、`flow._vis_try`）：高置信＋证人同字才给字，整理本在组里说了另一个字不越过。"""
from types import SimpleNamespace

import numpy as np

from open_guji_cv.groups import flow, vis_llm
from open_guji_cv.groups.flow import FlowConfig, _vis_try

CFG = FlowConfig(groups=("zy", "yz"), vis_model="m", vis_cache=None)
R = SimpleNamespace(id="vol01:1:1:1")
PATCH = lambda cid: np.zeros((20, 20), np.uint8)       # noqa: E731


def _ans(monkeypatch, ch, conf="high"):
    monkeypatch.setattr(vis_llm, "judge", lambda *a, **k: {"char": ch, "conf": conf, "why": "x", "cached": False})


def _try(cr, trail):
    return _vis_try("zy", R, trail, cr, CFG, lambda c: c, PATCH, "左", "右")


def test_ref_agrees(monkeypatch):
    _ans(monkeypatch, "千")
    ch, item = _try("千", [])
    assert ch == "千" and item["support"] == ["ref"]


def test_ctx_support_when_ref_missing(monkeypatch):
    _ans(monkeypatch, "予")
    ch, item = _try(None, [{"solver": "ctx", "char": "予"}])
    assert ch == "予" and item["support"] == ["ctx"]


def test_no_support(monkeypatch):
    _ans(monkeypatch, "予")
    ch, item = _try(None, [{"solver": "ctx", "char": None}])
    assert ch is None and item["why"].startswith("nosupport")


def test_not_over_ref_member(monkeypatch):
    _ans(monkeypatch, "于")
    ch, item = _try("干", [{"solver": "ctx", "char": "于"}])      # vol35:152:2:4 干文傳
    assert ch is None and item["why"].startswith("ref_dissent")


def test_low_conf(monkeypatch):
    _ans(monkeypatch, "千", "mid")
    ch, _ = _try("千", [])
    assert ch is None


def test_off_without_model(monkeypatch):
    _ans(monkeypatch, "千")
    cfg = FlowConfig(groups=("zy",))
    assert _vis_try("zy", R, [], "千", cfg, lambda c: c, PATCH, "左", "右") == (None, None)
