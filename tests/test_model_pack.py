# -*- coding: utf-8 -*-
"""模型系统第一期（`core/model_pack.py`）：模型卡、总号清单、册钉 model: N、补「钉语料的册换模型不过期」缺口。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_guji_cv.core import model_pack as mp


@pytest.fixture
def ws(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "models" / "partition_unet_v2").mkdir(parents=True)
    (repo / "models" / "partition_unet_v2" / "model.pt").write_bytes(b"unet")
    (repo / "models" / "README.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mp, "REPO_ROOT", repo)
    w = tmp_path / "book1"
    (w / "config" / "groups" / "l2model").mkdir(parents=True)
    (w / "config" / "groups" / "l2model" / "jys.json").write_text('{"w": 1}', encoding="utf-8")
    monkeypatch.delenv(mp.DRIFT_ENV, raising=False)
    mp._TOKEN.clear()
    mp._CLEAN.clear()
    return w


def test_collect_cards(ws):
    items = mp.collect(ws)
    by = {i["kind"]: i for i in items}
    assert set(by) == {"partition_unet", "l2_head"}
    assert by["partition_unet"]["level"] == "global" and by["partition_unet"]["owner"] == "global"
    assert by["l2_head"]["level"] == "book" and by["l2_head"]["owner"] == "book1"   # "*" = 所在的书
    assert by["l2_head"]["schema"] == mp.CARD_SCHEMA and len(by["l2_head"]["sha256"]) == 64


def test_build_once_and_bump(ws):
    r = mp.build(ws, note="first")
    assert r["version"] == 1 and mp.versions(ws) == [1]
    assert mp.build(ws)["unchanged"] == 1                       # 内容没变不出新号
    (ws / "config" / "groups" / "l2model" / "jys.json").write_text('{"w": 2}', encoding="utf-8")
    r2 = mp.build(ws)
    assert r2["version"] == 2 and r2["digest"] != mp.load_manifest(ws, 1)["digest"]
    with pytest.raises(ValueError):
        mp.build(ws, version=1)                                 # 清单只写一次


def test_require_clean(ws, monkeypatch):
    mp.build(ws)
    mp.require_model_clean(ws, 1)
    (ws / "config" / "groups" / "l2model" / "jys.json").write_text('{"w": 9}', encoding="utf-8")
    with pytest.raises(mp.ModelDrift):
        mp.require_model_clean(ws, 1)
    monkeypatch.setenv(mp.DRIFT_ENV, "warn")
    mp.require_model_clean(ws, 1)                               # 临时放行
    with pytest.raises(mp.ModelDrift):
        mp.require_model_clean(ws, 7)                           # 没有这号的清单


def test_pinned_group_flow_opt_in(ws, monkeypatch):
    mp.build(ws)
    monkeypatch.setattr("open_guji_cv.core.workspace.workspace_root", lambda: ws)
    assert mp.pinned_group_flow("corpus-v25", SimpleNamespace(model=None)) == "corpus-v25"   # 没钉：逐位不变
    tok = mp.pinned_group_flow("corpus-v25", SimpleNamespace(model=1))
    assert tok == "corpus-v25+" + mp.load_manifest(ws, 1)["digest"]


def test_parse_pin():
    assert mp.parse_pin(None) is None and mp.parse_pin("") is None
    assert mp.parse_pin(3) == 3 and mp.parse_pin("m4") == 4
    with pytest.raises(ValueError):
        mp.parse_pin("x")
