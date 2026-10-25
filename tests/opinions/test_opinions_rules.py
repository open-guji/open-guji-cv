# -*- coding: utf-8 -*-
"""意见池 C2：规则表各分支、修订推导、triage／to-user／decide 走一遍（数据自造）。"""
from __future__ import annotations

import json

import pytest
from booktext_fixture import BOOK, make
from booktext_fixture import char as fx_char
from booktext_fixture import cord as fx_cord

from open_guji_cv.opinions import rules as R
from open_guji_cv.opinions.schema import Opinion, make_id
from open_guji_cv.opinions.store import LocalBackend, OpinionStore
from open_guji_cv.opinions.textsrc import char_cells


def _op(n=1, **kw) -> Opinion:
    d = dict(id=make_id("charfix", f"k{n}"), book=BOOK, vol="002", channel="charfix", raw_id=f"r{n}",
             voter=f"v{n:05d}xxxxxxxxxx", ts="2026-10-20T00:00:00Z",
             target={"start": "3:1:2", "end": "3:1:2", "text_version": "1.0.1", "check": "定"},
             category="wrong", proposal={"text": "空"})
    d.update(kw)
    return Opinion(**d)


SEAL_OP = dict(channel="span", target={"start": "3:1:3", "end": "3:1:3", "text_version": "1.0.1", "check": "卷"},
               category="missing", proposal={"text": "卷一"})
A_REV = {"class": "A", "cells": [{"a": "3:1:2", "from": "定", "to": "空"}]}


def _route(op=None, **kw):
    base = dict(verdict="accept", confidence=0.99, public="图上是空", profile="published", revision=A_REV,
                status="new", evidence_agree=2)
    base.update(kw)
    return R.route(op or _op(), **base)


def test_auto_accept_and_thresholds():
    assert _route()[0] == "auto_accept"
    r, why = _route(confidence=0.9)
    assert r == "to_user" and "置信度" in why[0]
    assert _route(evidence_agree=1)[0] == "to_user"
    assert _route(revision={"class": "C", "cells": [{"a": "3:1:2"}]})[0] == "to_user"
    # 精校档门槛低
    assert _route(confidence=0.85, evidence_agree=1, profile="proofing")[0] == "auto_accept"


def test_auto_reject_needs_public_reason():
    assert _route(verdict="text_ok", revision=None)[0] == "auto_reject"
    assert _route(verdict="text_ok", revision=None, public="")[0] == "to_user"
    assert _route(verdict="text_ok", revision=None, confidence=0.5)[0] == "to_user"


def test_forward_drift_already():
    assert _route(_op(category="punct"))[0] == "forward"
    assert _route(verdict="out_of_scope")[0] == "forward"
    assert _route(status="forwarded")[0] == "forward"
    r, why = _route(located={"drift": "校验字 甲 ≠ 现文 乙"})
    assert r == "to_user" and "漂移" in why[0]
    assert _route(verdict="accept", located={"already": True, "drift": "已改"})[0] == "auto_accept"


def test_q7_lacuna_guess_goes_to_user():
    r, why = _route(_op(**SEAL_OP), verdict="lacuna_guess", confidence=0.99, revision=None)
    assert r == "to_user" and "Q7" in why[0]
    assert _route(verdict="seg_issue")[0] == "to_user" and _route(verdict="unclear")[0] == "to_user"


def test_figure_always_to_user():
    """GUJI-737：说是图形的意见不自动采纳也不自动驳回，一律交用户（建议里没有字，也推不出修订）。"""
    op = _op(category="figure", proposal={"choice": "figure", "alt": "圈点"})
    for verdict in ("accept", "text_ok"):
        r, why = _route(op, verdict=verdict, revision=None)
        assert r == "to_user" and "图形" in why[0]
    assert R.derive_revision(op, "accept", [{"a": "3:1:2", "c": "定"}], None) is None


def test_human_and_flood(tmp_path):
    assert _route(human_cells={"3:1:2"})[0] == "to_user"
    st = OpinionStore(BOOK, LocalBackend(tmp_path / BOOK)).load()
    other = st.add(_op(2, proposal={"text": "空"}))
    st.log(other.id, "decided", {"decision": "reject", "by": "user"})
    me = st.add(_op(3))
    r, why = _route(me, store=st)
    assert r == "to_user" and "用户已裁" in why[0]
    # 同一来源一天 60 条且多数与原文不同
    st2 = OpinionStore(BOOK, LocalBackend(tmp_path / "b2")).load()
    for i in range(60):
        st2.add(_op(100 + i, voter="floodxxxxxxxxxxx", target={"start": f"3:1:{i + 1}", "end": f"3:1:{i + 1}",
                                                                 "text_version": "1.0.1", "check": "甲"}))
    r, why = _route(next(iter(st2.opinions.values())), store=st2, human_cells=None)
    assert r == "to_user" and "刷票" in why[0]


def test_requested_route_only_more_conservative():
    assert _route(requested="to_user")[0] == "to_user"
    assert _route(requested="discuss")[0] == "discuss"
    with pytest.raises(R.RuleError):
        _route(verdict="text_ok", revision=None, confidence=0.1, requested="auto_reject")
    with pytest.raises(R.RuleError):
        _route(status="dup")


def test_derive_revision_classes():
    cells = char_cells(fx_char())
    pg = fx_cord()["pages"][2]
    a = R.derive_revision(_op(), "accept", cells, pg)
    assert a == {"class": "A", "cells": [{"a": "3:1:2", "from": "定", "to": "空"}]}
    b = R.derive_revision(_op(target={"start": "3:2:4", "end": "3:2:4", "text_version": "1.0.1", "check": "□"},
                              category="lacuna", proposal={"text": "之"}), "accept", cells, pg)
    assert b == {"class": "B", "cells": [{"a": "3:2:4", "from": "□", "to": "之"}]}
    b2 = R.derive_revision(_op(proposal={"text": "□"}), "accept", cells, pg)
    assert b2["class"] == "B" and b2["cells"][0]["lacuna"] is True
    bp = R.derive_revision(_op(**SEAL_OP), "lacuna_guess", cells, pg)
    assert bp == {"class": "B′", "cells": [{"a": "3:1:4", "after": "3:1:3", "mark": "mseal1", "from": "excluded",
                                            "to": "□", "lacuna": True, "guess": "一"}]}
    assert R.draft_event(bp) == {"v": "damaged", "cell": "3:1:4", "guess": "一",
                                 "note": "先移出排除名单（mark mseal1），再写事件"}
    # 旁边没有 mark：要插格，C 类
    c = R.derive_revision(_op(target={"start": "3:2:1", "end": "3:2:1", "text_version": "1.0.1", "check": "製"},
                              category="missing", proposal={"text": "製作"}), "accept", cells, pg)
    assert c["class"] == "C"


def test_next_key():
    assert R.next_key("3:1:9") == "3:1:10"
    assert R.next_key("3:4:-1") == "3:4:1"
    assert R.next_key("3:4:7a") == "3:4:8a"


def test_triage_to_user_decide_end_to_end(tmp_path, capsys):
    from open_guji_cv.cli_v2 import main
    bt = tmp_path / "bt"
    make(bt)
    st = OpinionStore(BOOK, LocalBackend(tmp_path / "pool" / BOOK)).load()
    q7 = st.add(_op(1, **SEAL_OP))
    a = st.add(_op(2))
    st.save()
    common = ["--book", BOOK, "--root", str(tmp_path / "pool"), "--book-text", str(bt)]
    main(["opinions", "triage", q7.id, *common, "--verdict", "lacuna_guess", "--confidence", "0.9",
          "--public", "图上无字，按文意当有「一」", "--judge", "test"])
    main(["opinions", "triage", a.id, *common, "--verdict", "accept", "--confidence", "0.99",
          "--public", "图上是空", "--evidence-agree", "2", "--judge", "test"])
    st = OpinionStore(BOOK, LocalBackend(tmp_path / "pool" / BOOK)).load()
    assert st.status(q7.id) == "to_user" and st.status(a.id) == "auto_accepted"
    tri = st.last(q7.id, "triaged").data
    assert tri["revision"]["class"] == "B′" and tri["revision"]["cells"][0]["guess"] == "一"
    assert tri["reply_draft"] == "感谢指正。图上无字，按文意当有「一」。"  # 不再把模板句与公开理由叠在一起（GUJI-713）
    out = tmp_path / "tu"
    main(["opinions", "to-user", "--book", BOOK, "--root", str(tmp_path / "pool"), "--out", str(out)])
    items = json.loads((out / "items.json").read_text(encoding="utf-8"))
    assert [i["id"] for i in items] == [q7.id]
    (tmp_path / "dec.json").write_text(json.dumps([{"id": q7.id, "decision": "accept"}]), encoding="utf-8")
    main(["opinions", "decide", "--book", BOOK, "--root", str(tmp_path / "pool"), "--from", str(tmp_path / "dec.json")])
    st = OpinionStore(BOOK, LocalBackend(tmp_path / "pool" / BOOK)).load()
    assert st.status(q7.id) == "accepted"
    assert st.cv_todo[0]["opinion"] == q7.id and st.cv_todo[0]["draft_event"]["guess"] == "一"
    main(["opinions", "reply-drafts", "--book", BOOK, "--root", str(tmp_path / "pool")])
    assert "待回复 2 条" in capsys.readouterr().out


def test_normalize_feedback(tmp_path):
    from open_guji_cv.cli_v2 import main
    st = OpinionStore(BOOK, LocalBackend(tmp_path / BOOK)).load()
    fb = st.add(Opinion(id=make_id("feedback", "fb:fb_1"), book=BOOK, vol="002", channel="feedback", raw_id="fb_1",
                        ts="2026-10-19T00:00:00Z", target={}, category="other", note="第二字错、末字漏"),
                log_data={"pending_normalize": True})
    st.save()
    into = json.dumps([{"target": {"start": "3:1:2", "end": "3:1:2", "text_version": "1.0.1", "check": "定"},
                        "category": "wrong", "proposal": {"text": "空"}},
                       {"target": {"start": "3:1:3", "end": "3:1:3", "text_version": "1.0.1", "check": "卷"},
                        "category": "missing", "proposal": {"text": "卷一"}}], ensure_ascii=False)
    main(["opinions", "normalize", fb.id, "--book", BOOK, "--root", str(tmp_path), "--into", into, "--by", "test"])
    st = OpinionStore(BOOK, LocalBackend(tmp_path / BOOK)).load()
    assert st.status(fb.id) == "superseded"
    new = [o for o in st.opinions.values() if o.normalized_by == "test"]
    assert len(new) == 2 and all(o.raw_id == "fb_1" and st.status(o.id) == "new" for o in new)
    assert st.last(fb.id, "superseded").data["all"] == [o.id for o in new]
