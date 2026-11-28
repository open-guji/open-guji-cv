# -*- coding: utf-8 -*-
"""换图源后待审单带 source_rev（GUJI-748）：数据全部自己造。
（2026-11-27 整张换单脚本退役，原「换单门／图源门」测试随 republish.py 删除。）
"""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401  注册产物种类
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"zhengli_{name}_ss", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _yaml(books: Path, book: str, rev: int | None) -> None:
    books.mkdir(parents=True, exist_ok=True)
    (books / f"{book}.yaml").write_text(f"id: {book}\n" + (f"source_rev: {rev}\n" if rev is not None else ""),
                                        encoding="utf-8")


def _cell_ev(key: str, seq: int, *, rev=None, migrated_from: str | None = None, ts="2026-10-20T00:00:00Z",
             payload=None, batch="b", step="seed_admit"):
    book, pg, col, slot = key.split(":")
    anchor = {}
    if rev is not None:
        anchor["source_rev"] = rev
    if migrated_from:
        anchor["migrated_from"] = {"key": migrated_from, "id": f"evt_old_{seq}"}
    e = make_event(batch, seq, "confirm",
                   EventTarget(step=step, unit="cell", key=key, book=book, page=int(pg), col=int(col),
                               slot=int(slot), anchor=anchor or None),
                   payload or {"v": "confirm", "shape": "甲"}, source_format="server")
    return e.model_copy(update={"ts": ts})



def test_pending_list_stamps_source_rev(tmp_path):
    pl = _load("pending_list")
    prod = tmp_path / "products"
    seed = prod / "vol06" / "seed_admit"
    seed.mkdir(parents=True)
    seed.joinpath("p0001.json").write_text(json.dumps({"seed_admit": {"n_review": 1, "columns": [{"chars": [
        {"id": "vol06:1:1:1", "admit": False}]}]}}), encoding="utf-8")
    args = ["--products", str(prod), "--book", "vol06", "--chapter", "006", "--rev", "006-r1", "--cv-commit", "x"]
    pl.main(args + ["--out", str(tmp_path / "a")])
    assert "source_rev" not in json.loads((tmp_path / "a" / "006.pending.json").read_text(encoding="utf-8"))
    (prod / "vol06" / "_source.json").write_text(json.dumps({"book_id": "abc", "vol": "6", "rev": 3}), encoding="utf-8")
    pl.main(args + ["--out", str(tmp_path / "b")])
    assert json.loads((tmp_path / "b" / "006.pending.json").read_text(encoding="utf-8"))["source_rev"] == 3

