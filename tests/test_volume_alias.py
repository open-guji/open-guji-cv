"""册旧名换新名（core/volume_alias；用户 11-27 定册号位数统一、老书 cv 册名也改）。"""
import json

import pytest

from open_guji_cv.core.event_files import iter_event_dicts
from open_guji_cv.core.volume_alias import alias_event_dict, alias_map, rename_key
from open_guji_cv.feedback.events import EventLog

AMAP = {"vol01": "01", "bxgb": "1"}


def test_rename_key_forms():
    assert rename_key("vol01:22:5:4", AMAP) == "01:22:5:4"
    assert rename_key("vol01/50:7:21", AMAP) == "01/50:7:21"
    assert rename_key("v2:vol01:102:1:3", AMAP) == "v2:vol01:102:1:3"   # 实例 id 不换
    assert rename_key("cols:vol01:171", AMAP) == "cols:01:171"
    assert rename_key("colborder:vol01:47:2:top", AMAP) == "colborder:01:47:2:top"
    assert rename_key("bxgb:3:1", AMAP) == "1:3:1"
    assert rename_key("vol01", AMAP) == "01"
    assert rename_key("vol02:22:5:4", AMAP) == "vol02:22:5:4"
    assert rename_key("p0042c03s17", AMAP) == "p0042c03s17"
    assert rename_key("vol01:22:5:4", {}) == "vol01:22:5:4"


def test_numeric_alias_does_not_touch_page_segment():
    # 脉经 01→1：新名事件 1:01:… 里的 01 是页号段，不能被当成旧册名换掉
    amap = {"01": "1"}
    assert rename_key("1:01:3:4", amap) == "1:01:3:4"
    assert rename_key("01:12:3:4", amap) == "1:12:3:4"
    assert rename_key("v2:01:12:3:4", amap) == "v2:01:12:3:4"
    assert rename_key("cols:01:171", amap) == "cols:1:171"


def test_alias_event_dict_fields_and_no_copy_when_clean():
    e = {"id": "vol01-x-1", "batch": "vol01-x", "target": {"book": "vol01", "key": "vol01:22:5:4", "step": "s"},
         "payload": {"cell": "vol01:22:5:4", "instance_id": "v2:vol01:22:5:4", "note": "vol01"},
         "book": "vol01"}
    out = alias_event_dict(e, AMAP)
    assert out["target"] == {"book": "01", "key": "01:22:5:4", "step": "s"}
    assert out["payload"] == {"cell": "01:22:5:4", "instance_id": "v2:vol01:22:5:4", "note": "vol01"}
    assert out["book"] == "01" and out["id"] == "vol01-x-1" and out["batch"] == "vol01-x"
    assert e["target"]["book"] == "vol01"                       # 不改入参
    clean = {"target": {"book": "05", "key": "05:1:1:1"}, "payload": {}}
    assert alias_event_dict(clean, AMAP) is clean


def _ws(tmp_path, aliases: bool):
    books = tmp_path / "books"
    books.mkdir()
    (books / "01.yaml").write_text("id: '01'\nvolume: 1\n" + ("aliases: [vol01]\n" if aliases else ""), encoding="utf-8")
    ev = tmp_path / "feedback" / "events"
    ev.mkdir(parents=True)
    rows = [{"id": "b-1", "ts": "2026-11-01T00:00:00", "batch": "b", "seq": 1, "kind": "confirm",
             "target": {"step": "seed_admit", "unit": "cell", "key": "vol01:22:5:4", "book": "vol01", "page": 22, "col": 5, "slot": 4},
             "payload": {"char": "己"}}]
    (ev / "b.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("aliases", [False, True])
def test_event_readers(tmp_path, aliases):
    root = _ws(tmp_path, aliases)
    log = EventLog(root / "feedback")
    want = ("01", "01:22:5:4") if aliases else ("vol01", "vol01:22:5:4")
    for e in (list(log.iter_all()) + list(log.iter_all_cached())):
        assert (e.target.book, e.target.key) == want
    d = next(iter_event_dicts(root / "feedback" / "events"))
    assert (d["target"]["book"], d["target"]["key"]) == want
    raw = next(iter_event_dicts(root / "feedback" / "events", gate=False))
    assert raw["target"]["book"] == "vol01"                         # 维护工具看原样
    assert list(log.read("b", raw=True))[0].target.book == "vol01"


def test_alias_map_conflict(tmp_path):
    (tmp_path / "1.yaml").write_text("aliases: [x]\n", encoding="utf-8")
    (tmp_path / "2.yaml").write_text("aliases: [x]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        alias_map(tmp_path)
    assert alias_map(tmp_path / "nope") == {}


def test_names_for(tmp_path):
    from open_guji_cv.core.volume_alias import names_for
    (tmp_path / "01.yaml").write_text('id: "01"\naliases: ["vol01"]\n', encoding="utf-8")
    (tmp_path / "02.yaml").write_text('id: "02"\n', encoding="utf-8")
    assert names_for("01", tmp_path) == {"01", "vol01"}
    assert names_for("02", tmp_path) == {"02"}


def test_pagemap_overrides_old_name_land_on_current_book():
    """改格表还写旧册名：as_vol 让它盖到本册的行上，而不是另补一行旧名（11-28 殿本演练）。"""
    from open_guji_cv.steps.row_segment_coltext import apply_overrides
    rows = [{"vol": "01", "page": 3, "col": 2, "slots": [1], "notes": [], "half": [], "raised": 0}]
    out = apply_overrides(rows, [{"vol": "vol01", "page": 3, "col": 2, "slots": [1, 2]}], as_vol="01")
    assert out == [{"vol": "01", "page": 3, "col": 2, "slots": [1, 2], "notes": [], "half": [], "raised": 0}]
    same = apply_overrides([dict(rows[0])], [{"vol": "01", "page": 3, "col": 2, "slots": [5]}])
    assert same[0]["slots"] == [5]
