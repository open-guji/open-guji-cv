# -*- coding: utf-8 -*-
"""语料库清单（ops.corpus_pack）：build 递增不覆盖、verify 能发现改动／缺失／新增。自造工作区，不碰真书数据。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.ops import corpus_pack as cp


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "config" / "groups").mkdir(parents=True)
    (tmp_path / "config" / "groups" / "freq.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙", encoding="utf-8")
    return tmp_path


def _ws_items(path):
    m = json.loads(path.read_text(encoding="utf-8"))
    return {i["path"] for i in m["items"] if i["root"] == "ws"}


def test_build_numbers_increase_and_never_overwrite(ws):
    p1 = cp.build(ws)
    assert p1.parent.name == "v1"
    assert _ws_items(p1) == {"config/groups/freq.json", "corpus/ref.txt"}
    assert cp.build(ws).parent.name == "v2"
    with pytest.raises(FileExistsError):
        cp.build(ws, 1)
    assert [s["version"] for s in cp.summary(ws)] == [1, 2]


def test_verify_detects_change_missing_extra(ws):
    cp.build(ws)
    assert cp.verify(ws, 1)["clean"]
    (ws / "config" / "groups" / "freq.json").write_text('{"a": 2}', encoding="utf-8")
    (ws / "corpus" / "ref.txt").unlink()
    (ws / "corpus" / "new.txt").write_text("丁", encoding="utf-8")
    r = cp.verify(ws, 1)
    assert not r["clean"]
    assert r["changed"] == ["ws:config/groups/freq.json"]
    assert r["missing"] == ["ws:corpus/ref.txt"]
    assert r["extra"] == ["ws:corpus/new.txt"]


def test_verify_unknown_version(ws):
    with pytest.raises(FileNotFoundError):
        cp.verify(ws, 9)
