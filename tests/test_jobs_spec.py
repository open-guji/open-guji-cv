# -*- coding: utf-8 -*-
"""任务库的任务定义：规整、校验、指纹（纯函数，不连库、不联网）。"""
from __future__ import annotations

import pytest

from open_guji_cv.jobs import spec as SP

C1 = "a" * 40
C2 = "b" * 40


def _resolve(ref: str) -> str:
    return {"v0.5.16": C1, "dev": C2}[ref]


def norm(**kw):
    return SP.normalize(kw, resolve=_resolve)


def test_defaults_filled_and_cv_resolved():
    s = norm(book="vol10", cv="v0.5.16", steps={"from": "seed_admit"})
    assert s["kind"] == "rerun" and s["cv"] == C1 and s["cv_ref"] == "v0.5.16"
    assert s["pipeline"] == SP.DEFAULT_PIPELINE and s["pages"] == "all"
    assert s["force"] is True and s["no_reuse"] is True
    assert s["base"] == "main"            # 从中间起跑缺省用 main 铺底
    assert s["output"] == {"change": None, "note": None, "pack": True}


def test_full_run_has_no_base_and_no_force_turns_reuse_back_on():
    s = norm(book="vol10", cv="dev", force=False)
    assert s["base"] is None and s["no_reuse"] is False


def test_hash_ignores_why_output_and_ref_spelling():
    a = norm(book="vol10", cv="v0.5.16", why="A24 要", output={"change": "x"})
    b = norm(book="vol10", cv=C1, why="A31 也要", output={"change": "y", "note": "n"})
    assert SP.spec_hash(a) == SP.spec_hash(b)


def test_hash_changes_with_config():
    a = norm(book="vol10", cv="v0.5.16")
    assert SP.spec_hash(a) != SP.spec_hash(norm(book="vol10", cv="dev"))
    assert SP.spec_hash(a) != SP.spec_hash(norm(book="vol10", cv="v0.5.16", book_overrides={"corpus": 16}))
    assert SP.spec_hash(a) != SP.spec_hash(norm(book="vol10", cv="v0.5.16", env={"GUJI_X": "1"}))


def test_override_order_does_not_matter():
    a = norm(book="vol10", cv="dev", book_overrides={"corpus": 16, "glyph_pin": 2}, env={"GUJI_B": 1, "GUJI_A": "x"})
    b = norm(book="vol10", cv="dev", book_overrides={"glyph_pin": "2", "corpus": 16}, env={"GUJI_A": "x", "GUJI_B": "1"})
    assert SP.spec_hash(a) == SP.spec_hash(b)


@pytest.mark.parametrize("kw, words", [
    ({"cv": "dev"}, "book"),
    ({"book": "vol10"}, "cv"),
    ({"book": "vol10", "cv": "dev", "colour": 1}, "不认识"),
    ({"book": "vol10", "cv": "dev", "env": {"GUJI_DATA_TOKEN": "x"}}, "凭据"),
    ({"book": "vol10", "cv": "dev", "env": {"PATH": "/x"}}, "GUJI_"),
    ({"book": "vol10", "cv": "dev", "book_overrides": {"raw_dir": "x"}}, "book_overrides"),
    ({"book": "vol10", "cv": "dev", "pin_args": "--x; rm -rf /"}, "shell"),
    ({"book": "vol10", "cv": "dev", "kind": "ab"}, "compare_to"),
    ({"book": "vol10", "cv": "dev", "pages": "all; ls"}, "pages"),
    ({"book": "vol10", "cv": "dev", "output": {"change": "中文"}}, "ASCII"),
    ({"book": "vol10", "cv": "dev", "run": [["status"]]}, "run"),
    ({"kind": "command", "cv": "dev", "run": [["db", "push"]]}, "子命令"),
    ({"kind": "command", "cv": "dev", "run": [["products", "pack", "push", "vol10"]]}, "fetch"),
    ({"kind": "command", "cv": "dev", "run": [["glyph-db", "push"]]}, "push"),
    ({"kind": "command", "cv": "dev", "run": [["products", "pack", "fetch", "vol1", "--main"]]}, "--main"),
    ({"kind": "command", "cv": "dev", "run": "eval run"}, "参数列表"),
])
def test_rejects(kw, words):
    with pytest.raises(SP.SpecError, match=words):
        norm(**kw)


def test_command_and_eval():
    s = norm(kind="command", cv="dev", book="vol10", run=[["guji", "status", "{book}", "-w", "{ws}"]])
    assert s["run"] == [["status", "{book}", "-w", "{ws}"]] and s["output"]["pack"] is False
    e = norm(kind="eval", cv="dev")
    assert e["run"] == [["eval", "run", "--json"]] and e["book"] is None


def test_compare_to_job():
    s = norm(kind="ab", book="vol10", cv="dev", compare_to={"job": 7})
    assert s["compare_to"] == {"job": 7}
    assert "比 #7" in SP.summary(s)


def test_unresolvable_cv_is_reported():
    def bad(ref):
        raise SP.SpecError(f"cv {ref!r} 找不到")
    with pytest.raises(SP.SpecError, match="找不到"):
        SP.normalize({"book": "vol10", "cv": "nope"}, resolve=bad)


def test_redact_hides_tokens():
    from open_guji_cv.jobs.runner import redact
    s = redact("GUJI_DATA_TOKEN=abc123 ok postgresql://u:p@h/db Bearer xyz")
    assert "abc123" not in s and "u:p" not in s and "xyz" not in s and "ok" in s


def test_book_overrides_accept_book_fields():
    """册级覆盖放开到 BookSpec 的字段（去掉身份与图源）；不认识的字段仍拒。"""
    a = norm(book="vol10", cv="dev", book_overrides={"cv_version": "0.5.21", "params": {"seed_admit": {"x": 1}}})
    assert a["book_overrides"]["cv_version"] == "0.5.21"
    with pytest.raises(SP.SpecError):
        norm(book="vol10", cv="dev", book_overrides={"nope": 1})


def test_glyph_diff_incremental_defaults():
    """改钉字形库只重算受影响的格（A32 精校前移 A4）：缺省从 glyph_match 起、不 force、复用照开。"""
    s = norm(book="vol10", cv="v0.5.16", glyph_diff=3, book_overrides={"glyph_pin": 5})
    assert s["glyph_diff"] == 3 and s["steps"] == {"from": "glyph_match", "to": None}
    assert s["force"] is False and s["no_reuse"] is False and s["base"] == "main"
    assert "glyph_diff" not in norm(book="vol10", cv="v0.5.16")       # 不给就没有这个键，老任务指纹不变
    for bad in ({"glyph_diff": 3}, {"glyph_diff": 3, "book_overrides": {"glyph_pin": 3}},
                {"glyph_diff": "3", "book_overrides": {"glyph_pin": 5}},
                {"glyph_diff": 3, "book_overrides": {"glyph_pin": 5}, "kind": "command", "run": [["status"]]}):
        with pytest.raises(SP.SpecError):
            norm(book="vol10", cv="v0.5.16", **bad)


def test_book_id_and_default_ws_repo():
    """册号（vol01）每部书都有：书 ID 取 ws_glob 的第一段，缺省殿本；已登记的书默认走自己的工作区仓，且不进指纹。"""
    base = {"kind": "rerun", "book": "vol01", "cv": "a" * 40}
    d = SP.normalize(base)
    assert SP.book_id(d) == "96mid1ogzk"
    assert d["ws_repo"] == "guji-workspace/96mid1ogzk-si-ku-zong-mu"
    q = SP.normalize({**base, "ws_glob": "995ejelvk0-*"})
    assert SP.book_id(q) == "995ejelvk0" and q["ws_repo"] is None
    assert SP.spec_hash(d) != SP.spec_hash(q)
    assert SP.spec_hash(d) == SP.spec_hash({**d, "ws_repo": None})
    assert SP.book_id({"ws_glob": "x*"}) is None
