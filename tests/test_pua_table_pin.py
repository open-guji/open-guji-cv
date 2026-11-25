# -*- coding: utf-8 -*-
"""PUA 码表共享层 `pua-wyg` 的读取侧：钉了读共享层、没钉读本书、副本缺／损坏报错、指纹只在钉了时变。"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from open_guji_cv.core import pua_table_pin as ptp
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _pua_pin
from open_guji_cv.utils.pua_v2_codes import load_table

ROWS = [{"code": "daizhige:U+EAA0", "verdict": "char", "char": "眩", "same_as": ["siku-qiefen-v2:U+F7001"]},
        {"code": "daizhige:U+EAA1", "verdict": "multi", "chars": ["瓠", "𤬄"], "same_as": ["siku-qiefen-v2:U+F7002"]}]


@pytest.fixture
def shared(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GUJI_DATA_BRANCH", raising=False)
    monkeypatch.delenv("GUJI_WORKSPACE", raising=False)
    from open_guji_cv.core.workspace import borrowed_root
    root = borrowed_root(ptp.PUA_WS, "main")

    def put(n, rows=ROWS):
        raw = ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode()
        d = ptp.version_dir(n, root)
        d.mkdir(parents=True, exist_ok=True)
        (d / ptp.TABLE_FILE).write_bytes(raw)
        (d / ptp.MANIFEST_FILE).write_text(json.dumps({"version": n, "sha256": hashlib.sha256(raw).hexdigest()}), encoding="utf-8")
        return d
    return put


def test_parse_pin():
    assert ptp.parse_pin(None) is None and ptp.parse_pin("v2") == 2 and ptp.parse_pin(3) == 3
    with pytest.raises(ValueError):
        ptp.parse_pin("abc")


def test_pinned_reads_shared_not_book(shared, tmp_path):
    shared(1)
    (tmp_path / "pua").mkdir()
    (tmp_path / "pua" / "pua_table.jsonl").write_text(json.dumps({"code": "siku-qiefen-v2:U+F7001", "verdict": "char", "char": "炫"}), encoding="utf-8")
    assert load_table(tmp_path)[0]["F7001"] == "炫"                       # 没钉：本书
    codes, fams = load_table(tmp_path, pin=1)
    assert codes["F7001"] == "眩" and fams["F7002"] == frozenset("瓠𤬄")   # 钉了：共享层，本书表不参与


def test_pinned_missing_or_corrupt_raises(shared):
    with pytest.raises(FileNotFoundError, match="没有 v4"):
        load_table(None, pin=4)
    d = shared(2)
    (d / ptp.TABLE_FILE).write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        load_table(None, pin=2)


def test_versions_independent(shared):
    shared(1)
    shared(2, ROWS[:1])
    assert "F7002" not in load_table(None, pin=2)[1] and "F7002" in load_table(None, pin=1)[1]


def test_digest_enters_params_only_when_pinned(shared):
    shared(1)
    book = SimpleNamespace(pua_table_pin=1)
    p = SeedAdmitParams(db_path="x", pua_code_table=True)
    q = ptp.with_pua_table_pin(p, book)
    assert q.pua_table_digest.startswith("pua-v1-") and q.model_dump()["pua_table_digest"] == q.pua_table_digest
    assert "pua_table_digest" not in p.model_dump()                          # 没钉：不进 dump，指纹不变
    assert ptp.with_pua_table_pin(p, SimpleNamespace(pua_table_pin=None)) is p
    off = SeedAdmitParams(db_path="x")
    assert ptp.with_pua_table_pin(off, book) is off                         # 没开码表的步不受影响


def test_book_field_and_seed_admit_pin():
    assert _pua_pin(None) is None and _pua_pin(SimpleNamespace(book=SimpleNamespace(pua_table_pin=3))) == 3
    from open_guji_cv.core.book import _parse_pua_table_pin
    assert _parse_pua_table_pin("v1") == 1 and _parse_pua_table_pin(None) is None
