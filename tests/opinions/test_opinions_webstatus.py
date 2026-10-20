# -*- coding: utf-8 -*-
"""意见池 → 网站状态清单（M11 B2，``guji opinions publish-status``）与回复草稿去重（GUJI-713）。数据全部自造。"""
from __future__ import annotations

import json

from open_guji_cv.opinions import rules as R
from open_guji_cv.opinions import webstatus as W
from open_guji_cv.opinions.schema import Opinion, make_id
from open_guji_cv.opinions.store import LocalBackend, OpinionStore

BOOK = "bk"


def _cf(n: int, cell: str, **kw) -> Opinion:
    d = dict(id=make_id("charfix", f"cf{n}"), book=BOOK, vol="002", channel="charfix",
             raw_id=f"cf:{BOOK}:002:1.0.1:{cell}", voter=f"v{n:05d}xxxxxxxxxx", ts=f"2026-10-20T00:00:0{n}Z",
             target={"start": cell, "end": cell, "text_version": "1.0.1", "check": "甲"},
             category="wrong", proposal={"text": "乙"})
    d.update(kw)
    return Opinion(**d)


def _span_public(n: int, s: str, e: str, sub: str = "missing", **kw) -> Opinion:
    d = dict(id=make_id("span", f"cs{n}"), book=BOOK, vol="002", channel="span",
             raw_id=f"span~{s}~{e}~{sub}~abc{n:03d}", voter=f"abc{n:03d}", ts=f"2026-10-20T00:01:0{n}Z",
             target={"start": s, "end": e, "text_version": "1.0.1", "check": "卷"},
             category="missing", proposal={"text": "卷一"}, extra={"sub": sub})
    d.update(kw)
    return Opinion(**d)


def _tri(public: str, verdict: str = "accept", route: str = "to_user", reply: str | None = None, **kw) -> dict:
    d = {"verdict": verdict, "confidence": 0.95, "rationale_public": public, "route": route, "judge": "t"}
    if reply is not None:
        d["reply_draft"] = reply
    d.update(kw)
    return d


def _store(tmp_path) -> OpinionStore:
    return OpinionStore(BOOK, LocalBackend(tmp_path / "pool" / BOOK)).load()


# ---- target、册号 ----

def test_web_target_and_volume():
    assert W.web_target(_cf(1, "3:1:2")) == "char~3:1:2~~"
    assert W.web_volume(_cf(1, "3:1:2", raw_id=f"cf:{BOOK}:vol02:1.0.1:3:1:2")) == "vol02"
    p = _span_public(1, "3:1:9", "3:1:9")
    assert W.web_target(p) == "span~3:1:9~3:1:9~missing" and W.web_volume(p) == "002"
    cs = _span_public(2, "3:1:5", "3:1:6", raw_id=f"cs:{BOOK}:002:1.0.1:3:1:5-3:1:6:wrong", extra={"sub": "wrong"})
    assert W.web_target(cs) == "span~3:1:5~3:1:6~wrong"
    ce = _span_public(3, "5:1:3", "5:1:4", raw_id=f"ce:{BOOK}:003:e001", category="entity",
                      extra={"entity_id": "e001"}, target={"start": "5:1:3", "end": "5:1:4", "entity_version": "1.0"})
    assert W.web_target(ce) == "entity~5:1:3~5:1:4~"
    cr = _cf(4, "3:1:2", channel="cellreview", id=make_id("cellreview", "x"),
             target={"start": "3:1:2", "end": "3:1:2", "rev": "002-r1"})
    assert W.web_target(cr) is None


# ---- 回复去重（GUJI-713）----

def test_reply_template_no_duplicate():
    op = _span_public(1, "3:1:9", "3:1:9")
    rev = {"class": "B′", "cells": [{"a": "3:1:10", "guess": "一"}]}
    public = "图上此格无字，据文意当有「一」"
    r = R.reply_template("lacuna_guess", rev, op, public)
    assert r == "感谢指正。图上此格无字，据文意当有「一」。"
    assert "推测字「一」" in R.reply_template("lacuna_guess", rev, op, "")
    # 旧写法（模板句＋公开理由叠在一起）存进池里的草稿：取正文时只留公开理由
    legacy = R.template_core("lacuna_guess", rev, op) + public
    tri = {"verdict": "lacuna_guess", "rationale_public": public, "reply_draft": legacy, "revision": rev}
    assert R.reply_body(tri, op) == public + "。"
    # 会话手写的草稿原样保留，只去掉开头致谢
    tri["reply_draft"] = "感谢指正，此处另有说明。"
    assert R.reply_body(tri, op) == "此处另有说明。"


# ---- 状态映射与聚合 ----

def test_compute_states(tmp_path):
    st = _store(tmp_path)
    applied = st.add(_cf(1, "3:1:2"))
    st.log(applied.id, "triaged", _tri("图上是乙", route="auto_accept"))
    st.log(applied.id, "applied", {"text_version": "1.0.2", "pr": "9"})
    acc = st.add(_span_public(2, "3:1:9", "3:1:9"))
    legacy = R.template_core("accept", None, acc) + "据文意当有「一」"
    st.log(acc.id, "triaged", _tri("据文意当有「一」", reply=legacy))
    st.log(acc.id, "decided", {"decision": "accept"})
    dup = st.add(_span_public(3, "3:1:9", "3:1:9"))
    st.log(dup.id, "dup", {"of": acc.id})
    rej = st.add(_cf(4, "4:1:1"))
    st.log(rej.id, "triaged", _tri("图上清楚是甲", verdict="text_ok", route="auto_reject",
                                   reply=R.reply_template("text_ok", None, _cf(4, "4:1:1"), "图上清楚是甲")))
    talk = st.add(_cf(5, "4:1:2"))
    st.log(talk.id, "triaged", _tri("要再看", verdict="unclear"))
    st.add(_cf(6, "4:1:3"))  # new：不写
    fwd = st.add(_span_public(7, "4:2:1", "4:2:2", sub="punct", category="punct"))
    st.log(fwd.id, "forwarded", {"to": "punct"})
    cr = st.add(_cf(8, "4:1:4", channel="cellreview", id=make_id("cellreview", "x"), raw_id="cr:002-r1:bk:4:1:4",
                    target={"start": "4:1:4", "end": "4:1:4", "rev": "002-r1"}))
    st.log(cr.id, "applied", {"text_version": "1.0.2"})  # 精校票不发

    rows, notes = W.compute(st)
    by = {r["target"]: r for r in rows}
    assert list(by) == ["char~3:1:2~~", "span~3:1:9~3:1:9~missing", "char~4:1:1~~", "char~4:1:2~~"]
    a = by["char~3:1:2~~"]
    assert a["state"] == "adopted" and a["version"] == "1.0.2"
    assert a["reply"] == "感谢指正，已采纳，已进文本 1.0.2。图上是乙。"
    b = by["span~3:1:9~3:1:9~missing"]
    assert b["state"] == "adopted" and "version" not in b
    assert b["reply"] == "感谢指正，已采纳，待随下一版文本更新。据文意当有「一」。"
    assert b["opinions"] == sorted([acc.id, dup.id])
    c = by["char~4:1:1~~"]
    assert c["state"] == "rejected" and c["reason"] == "图上清楚是甲" and "reply" not in c
    d = by["char~4:1:2~~"]
    assert d["state"] == "discussing" and d["reply"] == W.REPLY_DISCUSS
    assert all(r["volume"] == "002" and r["book"] == BOOK and r["v"] == 1 for r in rows)
    assert notes == []


def test_same_target_rank_and_replied(tmp_path):
    st = _store(tmp_path)
    x = st.add(_cf(1, "3:1:2"))
    st.log(x.id, "triaged", _tri("图上是甲", verdict="text_ok", route="auto_reject"))
    y = st.add(_cf(2, "3:1:2", proposal={"text": "丙"}))
    st.log(y.id, "triaged", _tri("图上是丙", route="auto_accept"))
    st.log(y.id, "replied", {"text": "谢谢，已改作丙。"})
    rows, _ = W.compute(st)
    assert len(rows) == 1
    r = rows[0]
    assert r["state"] == "adopted" and r["reply"] == "谢谢，已改作丙。" and "reason" not in r
    assert r["opinions"] == sorted([x.id, y.id])


# ---- 写文件：幂等 ----

def test_publish_idempotent(tmp_path):
    st = _store(tmp_path)
    o = st.add(_cf(1, "3:1:2"))
    st.log(o.id, "triaged", _tri("图上是乙", route="auto_accept"))
    be = LocalBackend(tmp_path / "web" / BOOK)
    r1 = W.publish(st, be, dry_run=True, ts="2026-10-20T01:00:00Z")
    assert r1["changed"] and not r1["written"] and not (tmp_path / "web" / BOOK / W.STATUS_FILE).exists()
    r1 = W.publish(st, be, ts="2026-10-20T01:00:00Z")
    assert r1["written"] and r1["counts"]["added"] == 1
    r2 = W.publish(st, be, ts="2026-10-21T01:00:00Z")
    assert not r2["changed"] and not r2["written"]
    assert r2["rows"][0]["ts"] == "2026-10-20T01:00:00Z"
    st.log(o.id, "applied", {"text_version": "1.0.2"})
    r3 = W.publish(st, be, ts="2026-10-22T01:00:00Z")
    assert r3["written"] and r3["counts"]["changed"] == 1
    row = json.loads((tmp_path / "web" / BOOK / W.STATUS_FILE).read_text(encoding="utf-8"))
    assert row["version"] == "1.0.2" and row["ts"] == "2026-10-22T01:00:00Z"


def test_cli_publish_status(tmp_path, capsys):
    from open_guji_cv.cli_v2 import main
    st = _store(tmp_path)
    o = st.add(_span_public(1, "3:1:9", "3:1:9"))
    st.log(o.id, "triaged", _tri("据文意当有「一」"))
    st.log(o.id, "decided", {"decision": "accept"})
    st.save()
    args = ["opinions", "publish-status", "--book", BOOK, "--root", str(tmp_path / "pool")]
    main([*args, "--dry-run"])
    assert not (tmp_path / "pool" / "_web" / BOOK / W.STATUS_FILE).exists()
    main(args)
    out = tmp_path / "pool" / "_web" / BOOK / W.STATUS_FILE
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["target"] == "span~3:1:9~3:1:9~missing" and row["state"] == "adopted"
    main(args)
    assert "内容没变" in capsys.readouterr().out
