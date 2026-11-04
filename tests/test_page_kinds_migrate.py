"""老写法 → page_kinds 迁移（ops/page_kinds_migrate.py）：保注释、逐步指纹核、冲突与空值。"""
from __future__ import annotations

import pytest

from open_guji_cv.core.book import load_book
from open_guji_cv.ops import page_kinds_migrate as M

HEAD = "id: {id}\ntitle: t\nraw_dir: raw\nexpected_cols: 9\n"
OLD_PARAMS = """# 册备注：别动
params:
  border_detect_gate:
    body_pages: [88, 90]   # 卷末叶
    table_pages: ["8-163"]
  row_segment:
    roster_pages: ["89-132"]
  seed_admit:
    shadow_veto: true
"""


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "books").mkdir()
    return tmp_path / "books"


def _w(ws, bid, tail):
    (ws / f"{bid}.yaml").write_text(HEAD.format(id=bid) + tail, encoding="utf-8")


def test_migrate_text_moves_and_keeps_other_params():
    new, info = M.migrate_text(HEAD.format(id="v") + OLD_PARAMS)
    assert info["moved"] == {"body": [88, 90], "table": ["8-163"], "roster": ["89-132"]}
    assert "# 册备注：别动" in new and "shadow_veto: true" in new
    assert "body_pages" not in new and "roster_pages" not in new
    assert new.index("page_kinds:") < new.index("params:")
    assert M.migrate_text(new)[0] is None                       # 幂等：改完再扫没东西了


def test_empty_params_section_removed_and_empty_values_dropped():
    new, info = M.migrate_text(HEAD.format(id="v") + "params:\n  row_segment:\n    roster_pages: [5]\n  border_detect_gate:\n    body_pages: []\n")
    assert info["moved"] == {"roster": [5]} and info["dropped"] == ["border_detect_gate.body_pages"]
    assert "params" not in new and "page_kinds:" in new


def test_no_old_form_returns_none():
    assert M.migrate_text(HEAD.format(id="v"))[0] is None
    assert M.migrate_text(HEAD.format(id="v") + "params:\n  seed_admit: {shadow_veto: true}\n")[0] is None


def test_conflict_with_existing_page_kinds():
    new, info = M.migrate_text(HEAD.format(id="v") + "page_kinds: {body: [1]}\nparams:\n  border_detect_gate: {body_pages: [2]}\n")
    assert new is None and "已有且与老写法不同" in info["conflict"]
    new, info = M.migrate_text(HEAD.format(id="v") + "page_kinds: {body: [1]}\nparams:\n  border_detect_gate: {body_pages: [1]}\n")
    assert info["conflict"] is None and "body_pages" not in new      # 值一样：只去掉老字段


def test_run_dry_then_apply_keeps_fingerprints(ws):
    _w(ws, "old1", OLD_PARAMS)
    _w(ws, "plain", "")
    res = M.run(ws)
    assert [(r["book"], r["status"]) for r in res] == [("old1", "dry")]
    assert "body_pages" in (ws / "old1.yaml").read_text(encoding="utf-8")      # 干跑不写
    before = M.step_fingerprints("old1", ws)
    res = M.run(ws, apply=True)
    assert res[0]["status"] == "migrated"
    assert "page_kinds:" in (ws / "old1.yaml").read_text(encoding="utf-8")
    assert M.step_fingerprints("old1", ws) == before                              # 真文件上再核一次
    assert load_book("old1", ws).page_kinds == {"body": [88, 90], "table": ["8-163"], "roster": ["89-132"]}
    assert M.run(ws) == []                                                         # 迁完没有老写法


def test_run_reports_conflict_and_only(ws):
    _w(ws, "bad", "page_kinds: {body: [1]}\nparams:\n  border_detect_gate: {body_pages: [2]}\n")
    _w(ws, "ok", "params:\n  row_segment: {roster_pages: [3]}\n")
    res = {r["book"]: r["status"] for r in M.run(ws)}
    assert res == {"bad": "conflict", "ok": "dry"}
    assert [r["book"] for r in M.run(ws, only=["ok"])] == ["ok"]
