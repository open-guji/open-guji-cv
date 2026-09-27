# -*- coding: utf-8 -*-
"""书级码位配置（字形库 11 §〇，2026-09-27）：`BookSpec.codepoints` 的读、
`canonical_char`/`codepoint_equal`，与 `set_codepoints` 的落盘往返。"""

from __future__ import annotations

from tests.helpers import make_book


def test_default_empty_is_identity():
    """没写 `codepoints` 时（缺省 {}），行为与加这个字段之前完全一样。"""
    book = make_book()
    assert book.codepoints == {}
    assert book.canonical_char("别") == "别"
    assert book.canonical_char("別") == "別"
    assert not book.codepoint_equal("别", "別")


def test_canonical_char_and_equal_with_mapping():
    book = make_book(codepoints={"别": "別", "内": "內"})
    assert book.canonical_char("别") == "別"
    assert book.canonical_char("別") == "別"          # 已是目标码位，原样返回
    assert book.canonical_char("强") == "强"           # 没配置的字不受影响
    assert book.codepoint_equal("别", "別")
    assert book.codepoint_equal("別", "別")
    assert not book.codepoint_equal("强", "強")        # 按形区分类不在这张表里


def test_to_dict_roundtrips_codepoints():
    book = make_book(codepoints={"别": "別"})
    assert book.to_dict()["codepoints"] == {"别": "別"}
    assert make_book().to_dict()["codepoints"] == {}


def test_set_codepoints_writes_and_load_book_reads_back(ws):
    from open_guji_cv.core.book import load_book, set_codepoints

    before = load_book("keben")
    assert before.codepoints == {}

    set_codepoints("keben", {"别": "別", "内": "內"})
    after = load_book("keben")
    assert after.codepoints == {"别": "別", "内": "內"}
    assert after.canonical_char("别") == "別"


def test_set_codepoints_preserves_existing_comments_and_fields(ws):
    from open_guji_cv.core.book import _book_yaml_path, load_book, set_codepoints

    path = _book_yaml_path("keben")
    before_text = path.read_text(encoding="utf-8")
    assert "测试专用册配置" in before_text        # 手写中文注释

    set_codepoints("keben", {"别": "別"})
    after_text = path.read_text(encoding="utf-8")
    assert "测试专用册配置" in after_text          # 注释没被 yaml.safe_dump 冲掉
    assert "codepoints:" in after_text

    book = load_book("keben")
    assert book.expected_cols == 8                 # 其余字段未受影响
    assert book.codepoints == {"别": "別"}


def test_set_codepoints_is_idempotent_on_rewrite(ws):
    """重复写同一份配置，块只出现一次、内容不重复堆叠。"""
    from open_guji_cv.core.book import _book_yaml_path, load_book, set_codepoints

    set_codepoints("keben", {"别": "別", "内": "內"})
    set_codepoints("keben", {"别": "別", "内": "內"})
    text = _book_yaml_path("keben").read_text(encoding="utf-8")
    assert text.count("codepoints:") == 1
    assert load_book("keben").codepoints == {"别": "別", "内": "內"}


def test_set_codepoints_can_update_and_clear(ws):
    from open_guji_cv.core.book import _book_yaml_path, load_book, set_codepoints

    set_codepoints("keben", {"别": "別"})
    set_codepoints("keben", {"别": "別", "内": "內"})   # 改：追加一对
    assert load_book("keben").codepoints == {"别": "別", "内": "內"}

    set_codepoints("keben", {})                         # 清空 = 回到不配置
    assert load_book("keben").codepoints == {}
    assert "codepoints:" not in _book_yaml_path("keben").read_text(encoding="utf-8")
