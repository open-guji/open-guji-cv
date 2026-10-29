# -*- coding: utf-8 -*-
"""意见池 D1a：修订工具 A／B／B′（自造小 char／cord 与一个桩 bump 脚本；真 book-text 的 local_check 不在测试里跑）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from booktext_fixture import BOOK, CHANGES_101, SEAL_BOX, make

from open_guji_cv.opinions import revise as V
from open_guji_cv.opinions.schema import Opinion, make_id
from open_guji_cv.opinions.store import LocalBackend, OpinionStore

#: 桩：照 book-text bump_original.py 的 patch 口径升版本（文本线：char version、index text_version，
#: 锚点全对得上的伴生层跟 text_version；伴生线：version 升、text_version 跟文本），并追加 CHANGES 一行。
BUMP_STUB = r'''
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("dir"); ap.add_argument("--line"); ap.add_argument("--level"); ap.add_argument("--chapter")
ap.add_argument("--note"); ap.add_argument("--pr")
a = ap.parse_args()
from open_guji_cv.opinions.revise import anchor_mismatches, dumps_compact
def bump(v):
    x, y, z = map(int, v.split(".")); return f"{x}.{y}.{z + 1}"
d = a.dir; ch = a.chapter
idx = json.load(open(os.path.join(d, "index.json"), encoding="utf-8"))
c = [x for x in idx["chapters"] if x["file"] == ch][0]
cp = os.path.join(d, f"{ch}.char.json"); char = json.load(open(cp, encoding="utf-8"))
if a.line == "text":
    old = char["version"]; new = bump(old); char["version"] = new; c["text_version"] = new
    open(cp, "w", encoding="utf-8").write(dumps_compact(char) + "\n")
    for comp in ("punct", "entity"):
        p = os.path.join(d, f"{ch}.{comp}.json")
        if os.path.exists(p):
            cd = json.load(open(p, encoding="utf-8"))
            if not anchor_mismatches(char, comp, cd):
                cd["text_version"] = new
                open(p, "w", encoding="utf-8").write(json.dumps(cd, ensure_ascii=False, indent=2) + "\n")
    line = "文本"
else:
    p = os.path.join(d, f"{ch}.{a.line}.json"); cd = json.load(open(p, encoding="utf-8"))
    bad = anchor_mismatches(char, a.line, cd)
    if bad:
        print("错误：" + "；".join(bad), file=sys.stderr); sys.exit(1)
    old = cd["version"]; new = bump(old); cd["version"] = new; cd["text_version"] = char["version"]
    c[f"{a.line}_version"] = new
    open(p, "w", encoding="utf-8").write(json.dumps(cd, ensure_ascii=False, indent=2) + "\n")
    line = {"punct": "标点", "entity": "实体"}[a.line]
json.dump(idx, open(os.path.join(d, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
with open(os.path.join(d, "CHANGES.md"), "a", encoding="utf-8") as f:
    f.write(f"| 2026-10-21 | bkxyz/{ch} | {line} | {old}→{new} | {a.note} | #{a.pr} |\n")
print(f"{line} {old}→{new}")
'''


@pytest.fixture
def bt(tmp_path) -> Path:
    root = tmp_path / "bt"
    make(root, changes=CHANGES_101)
    s = root / "scripts" / "book-text" / "bump_original.py"
    s.parent.mkdir(parents=True)
    s.write_text(BUMP_STUB, encoding="utf-8")
    return root


def _vd(bt: Path) -> Path:
    return bt / "Book" / "x" / "y" / "z" / BOOK / "default"


def _load(bt: Path, name: str):
    return json.loads((_vd(bt) / name).read_text(encoding="utf-8"))


def _op(i: int = 1) -> Opinion:
    return Opinion(id=make_id("charfix", f"k{i}"), book=BOOK, vol="002", channel="charfix", raw_id=f"r{i}",
                   ts=f"2026-10-20T00:00:0{i}Z", target={"start": "3:1:1", "end": "3:1:1", "text_version": "1.0.1"},
                   category="wrong")


def _cells(char):
    return [(c["a"], c["c"]) for p in char["pages"] for col in p["columns"] for c in col["cells"]]


def test_class_a_with_punct_follow_and_bump(bt):
    rev = {"class": "A", "cells": [{"a": "3:2:1", "from": "製", "to": "制"}]}
    res = V.revise(bt, BOOK, "002", [(_op(), rev)], dry_run=False, pr="301")
    assert res.problems == [] and res.old_version == "1.0.1" and res.new_version == "1.0.2"
    char, punct, idx = _load(bt, "002.char.json"), _load(bt, "002.punct.json"), _load(bt, "index.json")
    assert ("3:2:1", "制") in _cells(char) and char["version"] == "1.0.2"
    p = next(x for x in punct["punctuations"] if x.get("anchor") == "3:2:1")
    assert p["pre_char"] == "制" and punct["version"] == "1.1.1" and punct["text_version"] == "1.0.2"
    assert idx["chapters"][0]["text_version"] == "1.0.2" and idx["chapters"][0]["punct_version"] == "1.1.1"
    ch = (_vd(bt) / "CHANGES.md").read_text(encoding="utf-8")
    assert _op().id in ch and "3:2:1 製→制" in ch
    # char 仍是一格一行
    assert '{"a": "3:2:1", "c": "制"}' in (_vd(bt) / "002.char.json").read_text(encoding="utf-8")
    assert V.check_chapter(char, _load(bt, "002.cord.json"), punct, _load(bt, "002.entity.json"),
                           idx["chapters"][0]) == []


def test_class_b_both_directions(bt):
    revs = [(_op(1), {"class": "B", "cells": [{"a": "3:2:4", "from": "□", "to": "之"}]}),
            (_op(2), {"class": "B", "cells": [{"a": "3:2:5", "from": "文", "to": "□", "lacuna": True}]})]
    res = V.revise(bt, BOOK, "002", revs, dry_run=False, pr="302")
    assert res.problems == []
    char = _load(bt, "002.char.json")
    cells = {c["a"]: c for p in char["pages"] for col in p["columns"] for c in col["cells"]}
    assert cells["3:2:4"] == {"a": "3:2:4", "c": "之"}
    assert cells["3:2:5"] == {"a": "3:2:5", "c": "□", "lacuna": True}
    ent = _load(bt, "002.entity.json")
    assert next(e for e in ent["entities"] if e["id"] == "e2")["text"] == "□" and ent["version"] == "1.1.1"


def test_class_b_prime_mark_to_lacuna_cell(bt):
    rev = {"class": "B′", "cells": [{"a": "3:1:4", "after": "3:1:3", "mark": "mseal1", "from": "excluded",
                                     "to": "□", "lacuna": True, "guess": "一"}]}
    res = V.revise(bt, BOOK, "002", [(_op(), rev)], dry_run=False, pr="303")
    assert res.problems == []
    char, cord, punct, ent = (_load(bt, f"002.{k}.json") for k in ("char", "cord", "punct", "entity"))
    seq = _cells(char)
    i = seq.index(("3:1:3", "卷"))
    assert seq[i + 1] == ("3:1:4", "□") and seq[i + 2] == ("3:2:-1", "御")      # 插在「卷」之后、读序正确
    pg = cord["pages"][2]
    assert not any(m["id"] == "mseal1" for m in pg["marks"])
    assert {"a": "3:1:4", "box": SEAL_BOX, "id": "mseal1"} in pg["cells"]
    # 「卷」后的分段符挪到新格，后面的偏移都加一
    brk = next(p for p in punct["punctuations"] if p.get("kind") == "break")
    assert brk["anchor"] == "3:1:4" and brk["pre_char"] == "□" and brk["char_offset"] == 3
    assert [p["char_offset"] for p in punct["punctuations"]] == [0, 3, 5, 7, 10]
    assert [(e["span"]["start_offset"], e["span"]["end_offset"]) for e in ent["entities"]] == [(6, 8), (10, 11)]
    assert punct["version"] == "1.1.1" and ent["version"] == "1.1.1"    # 偏移变了，两条伴生线各升 patch
    assert "推测「一」" in (_vd(bt) / "CHANGES.md").read_text(encoding="utf-8")
    # 缺省写法 guess-c（GUJI-717）：新格带 guess_c，char 的 $schema 改写成 v0.2
    new_cell = next(c for p in char["pages"] for col in p["columns"] for c in col["cells"] if c["a"] == "3:1:4")
    assert new_cell == {"a": "3:1:4", "c": "□", "lacuna": True, "guess_c": "一"}
    assert char["$schema"] == V.CHAR_SCHEMA_V02
    # 自造数据和真书一样：mark 的 slot（3）与 char 格号（新格 4）口径不同，记一条说明
    assert len(res.applied[0].notes) == 1 and "slot 3" in res.applied[0].notes[0]


def test_b_prime_jiazhu_and_raised_columns(bt):
    """夹注列：mark 在左列（b）旁，插在 2b 之后成 3b；抬头列：-1 之后是 1 号格已有字 → 要改格号，拒绝（C 类）。"""
    char = json.loads((_vd(bt) / "002.char.json").read_text(encoding="utf-8"))
    cord = json.loads((_vd(bt) / "002.cord.json").read_text(encoding="utf-8"))
    rev = {"class": "B′", "cells": [{"a": "3:2:3b", "after": "3:2:2b", "mark": "mjz1", "from": "excluded", "to": "□",
                                     "lacuna": True}]}
    V.apply_one(char, cord, "op", rev)
    seq = [a for a, _c in _cells(char) if a.startswith("3:2:")]
    assert seq == ["3:2:-1", "3:2:1", "3:2:2a", "3:2:3a", "3:2:2b", "3:2:3b", "3:2:4", "3:2:5"]
    assert V.check_chapter(char, cord, None, None, None) == []
    with pytest.raises(V.ReviseError, match="已有字"):
        V.apply_one(char, cord, "op", {"class": "B′", "cells": [{"a": "3:2:1", "after": "3:2:-1", "mark": "mjz1"}]})


def test_guess_styles_and_guards(bt):
    base = {"class": "B′", "cells": [{"a": "3:1:4", "after": "3:1:3", "mark": "mseal1", "to": "□", "lacuna": True,
                                      "guess": "一"}]}
    for style, want in (("lacuna", {"a": "3:1:4", "c": "□", "lacuna": True}),
                        ("guess-char", {"a": "3:1:4", "c": "一", "guess": True}),
                        ("guess-c", {"a": "3:1:4", "c": "□", "lacuna": True, "guess_c": "一"})):
        char = json.loads((_vd(bt) / "002.char.json").read_text(encoding="utf-8"))
        cord = json.loads((_vd(bt) / "002.cord.json").read_text(encoding="utf-8"))
        ap = V.apply_one(char, cord, "op", base, style)
        assert ap.cells[0]["new"] == want
    char = json.loads((_vd(bt) / "002.char.json").read_text(encoding="utf-8"))
    with pytest.raises(V.ReviseError, match="版本对不上"):
        V.apply_one(char, {}, "op", {"class": "A", "cells": [{"a": "3:2:1", "from": "制", "to": "製"}]})
    with pytest.raises(V.ReviseError, match="第一阶段不做"):
        V.apply_one(char, {}, "op", {"class": "C", "cells": [{"a": "3:2:1"}]})
    with pytest.raises(V.ReviseError, match="--pr"):
        V.revise(bt, BOOK, "002", [(_op(), {"class": "A", "cells": [{"a": "3:2:1", "to": "制"}]})], dry_run=False)


def test_refuses_while_char_edits_pending(bt):
    (_vd(bt) / "002.char-edits.json").write_text("{}", encoding="utf-8")
    rev = {"class": "A", "cells": [{"a": "3:2:1", "from": "製", "to": "制"}]}
    with pytest.raises(V.ReviseError, match="改字清单"):
        V.revise(bt, BOOK, "002", [(_op(), rev)], dry_run=True)


def test_dry_run_writes_nothing(bt):
    before = {p.name: p.read_bytes() for p in _vd(bt).iterdir()}
    res = V.revise(bt, BOOK, "002", [(_op(), {"class": "A", "cells": [{"a": "3:2:1", "from": "製", "to": "制"}]})])
    assert res.new_version is None and res.problems == []
    assert {p.name: p.read_bytes() for p in _vd(bt).iterdir()} == before
    assert "製→制" in V.pr_body(res, BOOK)


def test_cli_plan_and_log_applied(bt, tmp_path, capsys):
    from open_guji_cv.cli_v2 import main
    st = OpinionStore(BOOK, LocalBackend(tmp_path / "pool" / BOOK)).load()
    a, b, c = st.add(_op(1)), st.add(_op(2)), st.add(_op(3))
    tri = {"verdict": "accept", "confidence": 0.99, "rationale_public": "x", "judge": "t"}
    st.log(a.id, "triaged", dict(tri, route="auto_accept", revision={"class": "A", "cells": [{"a": "3:2:1", "from": "製", "to": "制"}]}))
    st.log(b.id, "triaged", dict(tri, route="to_user", revision={"class": "C", "cells": [{"a": "3:2:1"}]}))
    st.log(b.id, "decided", {"decision": "accept"})
    st.log(c.id, "triaged", dict(tri, route="to_user", revision={"class": "A", "cells": [{"a": "3:1:1", "to": "钦"}]}))
    st.save()
    main(["opinions", "revise", "--book", BOOK, "--root", str(tmp_path / "pool"), "--vol", "002", "--book-text", str(bt),
          "--pr", "304", "--log-applied"])
    out = capsys.readouterr().out
    assert "要套 1 条，跳过 1 条" in out and "出口检查：通过" in out and "PR 正文" in out
    st = OpinionStore(BOOK, LocalBackend(tmp_path / "pool" / BOOK)).load()
    assert st.status(a.id) == "applied" and st.last(a.id, "applied").data == {"text_version": "1.0.2", "pr": "304"}
    assert st.status(c.id) == "to_user"
