"""gloss.py 单测：查询、注记与降级。构造小表，不依赖真实 gloss.json。"""

import json

import pytest

from open_guji_cv import gloss as G


@pytest.fixture()
def small_table(tmp_path, monkeypatch):
    t = {"仍": {"d": "依旧", "p": "réng", "s": "moe"},
         "乃": {"d": "于是", "p": "nǎi", "s": "moe"}}
    p = tmp_path / "gloss.json"
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(G, "DEFAULT_GLOSS_PATH", p)
    G._table.cache_clear()
    yield
    G._table.cache_clear()


def test_gloss_of(small_table):
    assert G.gloss_of("仍")["p"] == "réng"
    assert G.gloss_of("𠀀") == {}          # 缺字返回空 dict，不抛


def test_annotate_relations(small_table):
    info = G.annotate("仍", ("乃", "為"))
    assert any(r["char"] == "乃" and r["kind"] == "通假"
               for r in info.get("rel", []))
    assert all(r["char"] != "為" for r in info.get("rel", []))


def test_annotate_missing_table(tmp_path, monkeypatch):
    """gloss.json 不存在时静默降级：无释义但关系注记仍然工作。"""
    monkeypatch.setattr(G, "DEFAULT_GLOSS_PATH", tmp_path / "nope.json")
    G._table.cache_clear()
    info = G.annotate("為", ("爲",))
    assert "d" not in info
    assert any(r["kind"] == "異體" for r in info.get("rel", []))
    G._table.cache_clear()
