# -*- coding: utf-8 -*-
"""提示词模板渲染（groups.prompt_template）：占位符用书层变量填，缺了就报错，没占位符与原样一致。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.groups.ctx_l3 import build_batch, load_prompt
from open_guji_cv.groups.prompt_template import (book_prompt_vars, build_batch_rendered,
                                                 load_rendered_prompt)


def test_placeholders_filled_and_missing_raises(tmp_path):
    p = tmp_path / "prompt.md"
    p.write_text("---\nver: x\n---\n下面是{{book_desc}}的字位。", encoding="utf-8")
    assert load_rendered_prompt(p, {"book_desc": "《某書》刻本"})[1] == "下面是《某書》刻本的字位。"
    with pytest.raises(KeyError, match="book_desc"):
        load_rendered_prompt(p)
    cells = [{"id": "c1", "left": "甲", "right": "乙"}]
    assert "《某書》刻本" in build_batch_rendered(p, cells, {"book_desc": "《某書》刻本"})


def test_plain_prompt_is_identical_to_ctx_l3(tmp_path):
    p = tmp_path / "plain.md"
    p.write_text("---\nver: x\n---\n没有占位符{x}", encoding="utf-8")
    assert load_rendered_prompt(p, {"a": "b"}) == load_prompt(p)
    cells = [{"id": "c1", "left": "甲", "right": "乙"}]
    assert build_batch_rendered(p, cells) == build_batch(p, cells)


def test_book_prompt_vars_reads_data_root_config(tmp_path):
    assert book_prompt_vars(tmp_path) == {}
    (tmp_path / "config" / "groups").mkdir(parents=True)
    (tmp_path / "config" / "groups" / "book_prompt.json").write_text(
        json.dumps({"book_desc": "X"}, ensure_ascii=False), encoding="utf-8")
    assert book_prompt_vars(tmp_path) == {"book_desc": "X"}
