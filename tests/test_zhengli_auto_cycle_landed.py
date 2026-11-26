"""auto_cycle 判 fresh 也认收尾落定记录 reports/<册>/_land/landed.json（GM4 换包按条目对账，11-24）。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("zl_auto_cycle_landed", SCRIPTS / "auto_cycle.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


def _ws(tmp_path, landed=None):
    ws = tmp_path / "ws"
    tmp_path.mkdir(parents=True, exist_ok=True)
    sheet = tmp_path / "sheet.json"
    sheet.write_text(json.dumps({"rev": "005-r7"}), encoding="utf-8")
    if landed is not None:
        f = ws / "reports" / "vol05" / "_land" / "landed.json"
        f.parent.mkdir(parents=True)
        f.write_text(landed, encoding="utf-8")
    return ws, sheet


def _patch(monkeypatch, sheet):
    monkeypatch.setattr(ac.rp, "text_id_of", lambda ws: "t")
    monkeypatch.setattr(ac.rp, "chapter_of", lambda b: "005")
    monkeypatch.setattr(ac.rp, "proofing_path", lambda ws, t, c: sheet)
    monkeypatch.setattr(ac, "pack_rows", lambda ws, b: [{"label": "r9", "main": True, "time": "t", "note": ""}])


def test_landed_on_current_main_is_fresh(tmp_path, monkeypatch):
    ws, sheet = _ws(tmp_path, json.dumps({"digest": "d", "pack": "r9"}))
    _patch(monkeypatch, sheet)
    r = ac.decide(ws, "vol05")
    assert r["verdict"] == "fresh" and r["online_rev"] == "005-r7"


def test_landed_on_older_pack_or_broken_is_not_fresh(tmp_path, monkeypatch):
    for body in (json.dumps({"digest": "d", "pack": "r8"}), "{坏", "[]"):
        ws, sheet = _ws(tmp_path / body.encode().hex()[:8], body)
        _patch(monkeypatch, sheet)
        monkeypatch.setattr(ac.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("走到 status")))
        try:
            r = ac.decide(ws, "vol05")
        except RuntimeError:
            continue                       # 没判 fresh，往下走到查票：对
        assert r["verdict"] != "fresh"
    assert ac.landed_pack(tmp_path / "none", "vol05") is None
