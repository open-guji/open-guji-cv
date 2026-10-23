# -*- coding: utf-8 -*-
"""意见池 A1：schema 与 store（设计 `doc/design/M11-分块-第一阶段最小闭环.md` 第二节）。数据全部自造。"""
from __future__ import annotations

import json

import jsonschema
import pytest

from open_guji_cv.opinions import schema as S
from open_guji_cv.opinions.store import (
    DuplicateId,
    LocalBackend,
    OpinionStore,
    StoreConflict,
    open_store,
)


def _op(n: int = 1, **kw) -> S.Opinion:
    d = dict(id=S.make_id("charfix", f"cf:bk:002:1.0.0:3:1:{n}|abcdef"), book="bk", vol="002", channel="charfix",
             raw_id=f"cf:bk:002:1.0.0:3:1:{n}", voter="abcdef0123456789", ts="2026-10-20T01:00:00Z",
             target={"start": f"3:1:{n}", "end": f"3:1:{n}", "text_version": "1.0.0", "check": "甲"},
             category="wrong", proposal={"text": "乙"})
    d.update(kw)
    return S.Opinion(**d)


def _store(tmp_path) -> OpinionStore:
    return OpinionStore("bk", LocalBackend(tmp_path / "bk")).load()


def test_roundtrip(tmp_path):
    st = _store(tmp_path)
    a, b = st.add(_op(1)), st.add(_op(2, note="读者原话"))
    st.log(a.id, "triaged", {"verdict": "text_ok", "confidence": 0.9, "rationale_public": "图上是甲",
                             "route": "auto_reject", "judge": "test"})
    st.add_cv_todo({"opinion": b.id, "event": {"v": "confirm"}})
    st.merge_raw({"id": "fb_1", "content": "x"})
    st.set_text_versions({"002": [{"text_version": "1.0.0"}]})
    st.save()
    st2 = _store(tmp_path)
    assert [o.to_dict() for o in st2.opinions.values()] == [a.to_dict(), b.to_dict()]
    assert [e.kind for e in st2.events] == ["ingested", "ingested", "triaged"]
    assert st2.raw == {"fb_1": {"id": "fb_1", "content": "x"}}
    assert st2.text_versions == {"002": [{"text_version": "1.0.0"}]}
    assert st2.cv_todo == [{"opinion": b.id, "event": {"v": "confirm"}}]
    assert st2.status(a.id) == "auto_rejected" and st2.status(b.id) == "new"


def test_duplicate_id_rejected(tmp_path):
    st = _store(tmp_path)
    st.add(_op(1))
    with pytest.raises(DuplicateId):
        st.add(_op(1))
    st.save()
    st2 = _store(tmp_path)
    with pytest.raises(DuplicateId):
        st2.add(_op(1, note="改了也不行"))
    # 文件里重复的 id 也报
    p = tmp_path / "bk" / "opinions.jsonl"
    p.write_text(p.read_text(encoding="utf-8") * 2, encoding="utf-8")
    with pytest.raises(DuplicateId):
        _store(tmp_path)


def test_append_keeps_old_bytes_and_detects_conflict(tmp_path):
    st = _store(tmp_path)
    st.add(_op(1))
    st.save()
    p = tmp_path / "bk" / "log.jsonl"
    old = p.read_text(encoding="utf-8")
    st2 = _store(tmp_path)
    st2.add(_op(2))
    st2.save()
    assert p.read_text(encoding="utf-8").startswith(old)
    # 读后被别人改了：不覆盖
    st3 = _store(tmp_path)
    st3.add(_op(3))
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(StoreConflict):
        st3.save()


def _ev(kind, **data):
    return S.LogEvent(ts="t", opinion="op", kind=kind, by="x", data=data)


TRI = dict(confidence=0.5, rationale_public="理由", judge="j")


@pytest.mark.parametrize("events,want", [
    ([], "new"),
    ([_ev("ingested")], "new"),
    ([_ev("ingested", pending_normalize=True)], "to_normalize"),
    ([_ev("ingested", pending_normalize=True), _ev("superseded", by="op2")], "superseded"),
    ([_ev("ingested"), _ev("dup", of="op0")], "dup"),
    ([_ev("ingested"), _ev("forwarded", to="punct")], "forwarded"),
    ([_ev("triaged", verdict="accept", route="auto_accept", **TRI)], "auto_accepted"),
    ([_ev("triaged", verdict="text_ok", route="auto_reject", **TRI)], "auto_rejected"),
    ([_ev("triaged", verdict="lacuna_guess", route="to_user", **TRI)], "to_user"),
    ([_ev("triaged", verdict="unclear", route="discuss", **TRI)], "discussing"),
    ([_ev("triaged", verdict="out_of_scope", route="forward", **TRI)], "forwarded"),
    ([_ev("triaged", verdict="accept", route="to_user", **TRI), _ev("decided", decision="accept")], "accepted"),
    ([_ev("triaged", verdict="accept", route="to_user", **TRI), _ev("decided", decision="reject")], "rejected"),
    ([_ev("triaged", verdict="accept", route="to_user", **TRI), _ev("decided", decision="discuss")], "discussing"),
    ([_ev("decided", decision="accept"), _ev("applied", text_version="1.0.2", pr="#1")], "applied"),
    ([_ev("decided", decision="accept"), _ev("applied", text_version="1.0.2"), _ev("replied", text="谢谢"),
      _ev("cv_written", batch="b")], "applied"),
    # 自动化新增的 kind：只有 reverted 改状态，发布批进度看 releases.jsonl
    ([_ev("decided", decision="accept"), _ev("batched", release="r1"), _ev("pr_opened", release="r1", pr="3"),
      _ev("policy_applied", rule="x")], "accepted"),
    ([_ev("decided", decision="accept"), _ev("applied", text_version="1.0.2"), _ev("published", release="r1")], "applied"),
    ([_ev("decided", decision="accept"), _ev("applied", text_version="1.0.2"),
      _ev("reverted", release="r1", reason="改错了")], "reverted"),
])
def test_status_covers_every_kind(events, want):
    assert S.derive_status(events) == want


def test_every_log_kind_is_covered():
    """上面的表覆盖了 schema 里的每个 log kind。"""
    seen = {"ingested", "superseded", "dup", "forwarded", "triaged", "decided", "applied", "replied", "cv_written",
            "batched", "pr_opened", "published", "reverted", "policy_applied"}
    assert seen == set(S.LOG_KINDS)


def test_log_validation(tmp_path):
    st = _store(tmp_path)
    a = st.add(_op(1))
    with pytest.raises(S.SchemaError):
        st.log(a.id, "dup")                       # 缺 of
    with pytest.raises(S.SchemaError):
        st.log(a.id, "triaged", {"verdict": "text_ok", "confidence": 0.9, "route": "auto_reject", "judge": "j"})  # 自动结案缺公开理由
    with pytest.raises(S.SchemaError):
        st.log(a.id, "nope")
    with pytest.raises(KeyError):
        st.log("op_charfix_0000000000", "ingested")


def test_opinion_validation():
    with pytest.raises(S.SchemaError):
        _op(1, category="typo").validate()
    with pytest.raises(S.SchemaError):
        _op(1, target={"start": "3:1:x", "end": "3:1:1", "text_version": "1"}).validate()
    with pytest.raises(S.SchemaError):
        _op(1, target={"start": "3:1:1", "end": "3:1:1"}).validate()   # 格号没版本
    with pytest.raises(S.SchemaError):
        S.Opinion.from_dict(dict(_op(1).to_dict(), bogus=1))


def test_json_schema_accepts_tool_output(tmp_path):
    sch = S.json_schema()
    st = _store(tmp_path)
    st.add(_op(1, extra={"basis": "x"}))
    st.save()
    for line in (tmp_path / "bk" / "opinions.jsonl").read_text(encoding="utf-8").splitlines():
        jsonschema.validate(json.loads(line), sch)
    bad = dict(_op(1).to_dict(), category="typo")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, sch)


def test_open_store_root_and_ids(tmp_path):
    st = open_store("bk", root=tmp_path)
    assert st.backend.describe().endswith("bk")
    i = S.make_id("machine:l1", "k", 2)
    assert i.startswith("op_machine-l1_") and i.endswith("_2") and S.ID_RE.match(i)
    assert S.norm_class("B'") == "B′"
