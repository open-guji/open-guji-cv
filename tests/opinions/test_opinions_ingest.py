# -*- coding: utf-8 -*-
"""意见池 A2：三源入池（设计 A2 验收：三源各 3 条，含重复、测试票、专名 → 入池 7、forwarded 1、dup 1；重跑新增 0）。"""
from __future__ import annotations

import json

from open_guji_cv.opinions import ingest as I
from open_guji_cv.opinions.store import LocalBackend, OpinionStore

BOOK = "bk01"
T0 = 1792460026957


def _fixes() -> list[dict]:
    return [
        {"v": 1, "kind": "char", "book_id": BOOK, "volume": "002", "text_version": "1.0.1", "cell_id": "3:2:1",
         "old_char": "經", "new_char": "经", "basis": "联系我 reader@example.com", "voter": "aaaaaa1111111111", "ts": T0},
        {"v": 1, "kind": "span", "book_id": BOOK, "volume": "002", "text_version": "1.0.1", "start": "3:1:9", "end": "3:1:9",
         "sub": "missing", "old_text": "卷", "new_text": "卷一", "note": "后面是印章", "voter": "0100881111111111", "ts": T0 + 1},
        {"v": 1, "kind": "entity", "book_id": BOOK, "volume": "002", "chapter": "002", "entity_id": "e01384",
         "entity_version": "1.10.0", "anchor": {"start": "3:7:17", "end": "3:7:18"}, "text": "王弼", "note": "不是人名",
         "voter": "bbbbbb1111111111", "ts": T0 + 2},
    ]


def _votes() -> list[dict]:
    return [
        {"v": 1, "book": BOOK, "vol": "001", "a": "9:7:17", "rev": "001-r2", "choice": "char", "char": "臼", "note": "",
         "shown": "□", "voter": "dd04f7895bf5d5d8", "ts": T0 - 200000000},
        {"v": 1, "book": BOOK, "vol": "001", "a": "9:7:17", "rev": "001-r2", "choice": "char", "char": "臼", "note": "",
         "shown": "", "voter": "827b7158c22cb788", "ts": T0 - 100000000},
        {"v": 1, "book": BOOK, "vol": "vol01", "a": "9:7:17", "rev": "001-r2", "choice": "char", "char": "曾",
         "note": "【测试】验收，请排除", "shown": "□", "voter": "454b3d51dbcdedb8", "ts": T0 - 300000000},
    ]


def _feedback() -> list[dict]:
    return [
        {"id": "fb_1_aaaa", "type": "bug", "content": "【原文】欽定\n\n第二字错了，电话 13812345678", "pageUrl": f"https://x/read/{BOOK}/002#rd-e-3",
         "createdAt": "2026-10-19T00:00:00.000Z", "status": "pending", "category": "typo"},
        {"id": "fb_2_bbbb", "type": "bug", "content": "有漏字", "pageUrl": f"https://x/item/{BOOK}", "resourceId": BOOK,
         "createdAt": "2026-10-19T01:00:00.000Z", "status": "pending", "category": "typo"},
        {"id": "fb_3_cccc", "type": "bug", "content": "页面空白", "pageUrl": "https://x/book-index",
         "createdAt": "2026-10-19T02:00:00.000Z", "status": "pending", "category": "site"},
    ]


def _src(**kw) -> I.Sources:
    return I.Sources(fixes=_fixes(), cellreview={"001-r2.jsonl": _votes()}, feedback=_feedback(), **kw)


def _store(tmp_path) -> OpinionStore:
    return OpinionStore(BOOK, LocalBackend(tmp_path / BOOK)).load()


def test_three_sources_acceptance(tmp_path):
    st = _store(tmp_path)
    rep = I.ingest(st, I.incoming(_src(), BOOK))
    st.save()
    assert len(rep.added) == 7
    assert len(rep.forwarded) == 1 and len(rep.dup) == 1
    assert rep.dropped == {"测试票": 1, "非文字类": 1}
    stat = _store(tmp_path).statuses()
    assert sorted(stat.values()) == sorted(["new", "new", "forwarded", "new", "dup", "to_normalize", "to_normalize"])
    chans = sorted(o.channel for o in st.opinions.values())
    assert chans == ["cellreview", "cellreview", "charfix", "feedback", "feedback", "span", "span"]
    # 后投的那张是重复，指向先投的
    cr = sorted((o for o in st.opinions.values() if o.channel == "cellreview"), key=lambda o: o.ts)
    assert stat[cr[1].id] == "dup" and st.last(cr[1].id, "dup").data["of"] == cr[0].id
    # 通用反馈原样存档、正文脱敏
    st2 = _store(tmp_path)
    assert set(st2.raw) == {"fb_1_aaaa", "fb_2_bbbb"}
    fb = [o for o in st2.opinions.values() if o.raw_id == "fb_1_aaaa"][0]
    assert "13812345678" not in fb.note and fb.vol == "002"
    cf = [o for o in st2.opinions.values() if o.channel == "charfix"][0]
    assert cf.note == "联系我 ***@***" and cf.target == {"start": "3:2:1", "end": "3:2:1", "text_version": "1.0.1", "check": "經"}
    # 重跑新增 0
    st3 = _store(tmp_path)
    rep2 = I.ingest(st3, I.incoming(_src(), BOOK))
    assert rep2.added == [] and rep2.existing == 7 and st3.pending()["log"] == 0


def test_public_live_read_matches_snapshot_id(tmp_path):
    """公开实时读 /api/fixes 进来的那条，日后同步进 fixes.jsonl 不会再入一次。"""
    live = {"success": True, "book": BOOK, "volumes": {"002": [
        {"kind": "span", "at": "3:1:9", "who": "010088", "ts": T0 + 1, "tv": "1.0.1", "end": "3:1:9", "sub": "missing",
         "old": "卷", "new": "卷一", "note": "后面是印章"}]}}
    st = _store(tmp_path)
    rep = I.ingest(st, I.incoming(I.Sources(public_fixes=[live]), BOOK))
    assert len(rep.added) == 1
    op = st.opinions[rep.added[0]]
    assert op.raw_id == "span~3:1:9~3:1:9~missing~010088" and op.category == "missing"
    assert op.proposal == {"text": "卷一"} and op.target["check"] == "卷"
    rep2 = I.ingest(st, I.incoming(I.Sources(fixes=_fixes()[1:2]), BOOK))
    assert rep2.added == [] and rep2.existing == 1


def test_same_voter_changed_mind_supersedes(tmp_path):
    st = _store(tmp_path)
    I.ingest(st, I.incoming(I.Sources(fixes=_fixes()[:1]), BOOK))
    changed = dict(_fixes()[0], new_char="𦆀", ts=T0 + 50)
    rep = I.ingest(st, I.incoming(I.Sources(fixes=[changed]), BOOK))
    assert len(rep.superseded) == 1
    old, new = rep.superseded[0]
    assert new == old + "_2" and st.status(old) == "superseded" and st.status(new) == "new"
    rep2 = I.ingest(st, I.incoming(I.Sources(fixes=[changed, _fixes()[0]]), BOOK))
    assert rep2.added == []


def test_hidden_and_other_book(tmp_path):
    f = _fixes()[0]
    hidden = {f"cf|002|1.0.1|3:2:1|{f['voter']}"}
    items = I.incoming(I.Sources(fixes=[f, dict(f, book_id="other")], hidden=hidden), BOOK)
    assert [i.drop for i in items] == ["站方隐藏", "不是本书"]


def test_read_dir(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    (d / "fixes.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _fixes()), encoding="utf-8")
    (d / "001-r2.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _votes()), encoding="utf-8")
    (d / "api-feedback.json").write_text(json.dumps({"items": _feedback()}, ensure_ascii=False), encoding="utf-8")
    src = I.read_dir(d)
    assert len(src.fixes) == 3 and len(src.cellreview["001-r2.jsonl"]) == 3 and len(src.feedback) == 3


def test_desensitize():
    assert I.desensitize("QQ: 12345678 微信号abcde_1 vx: wxid_x9") == "QQ: *** 微信号*** vx: ***"
    assert I.desensitize("身份证 110101199003071234") == "身份证 ***"


def test_figure_from_three_paths():
    """GUJI-737：读者说「这是图形，不是字」——网站改字（KV 原值、公开实时读）与精校票都入 figure 类，建议里不放字。"""
    r = {"v": 1, "kind": "char", "book_id": BOOK, "volume": "005", "text_version": "1.0.1", "cell_id": "148:2:14",
         "old_char": "〇", "new_char": "□", "figure": True, "alt": "左半圈连一实点", "voter": "aaaaaa1111111111", "ts": T0}
    op = I.from_fix_record(r, BOOK).op
    assert op.category == "figure" and op.proposal == {"choice": "figure", "alt": "左半圈连一实点"}
    assert op.validate()
    live = {"book": BOOK, "volumes": {"005": [{"kind": "char", "at": "148:2:14", "tv": "1.0.1", "old": "〇", "new": "□",
                                                "fig": 1, "who": "aaaaaa", "ts": T0}]}}
    op2 = I.from_public_fixes(live, BOOK)[0].op
    assert op2.category == "figure" and op2.proposal == {"choice": "figure"}
    plain = I.from_fix_record({**r, "figure": None, "alt": None, "new_char": "○"}, BOOK).op
    assert plain.category == "wrong" and plain.proposal == {"text": "○"}
    v = {"v": 1, "book": BOOK, "vol": "005", "a": "148:2:14", "rev": "005-r1", "choice": "figure", "alt": "圈点",
         "note": "", "shown": "〇", "voter": "dd04f7895bf5d5d8", "ts": T0}
    op3 = I.from_cellreview(v, BOOK).op
    assert op3.category == "figure" and op3.proposal == {"choice": "figure", "alt": "圈点"}
