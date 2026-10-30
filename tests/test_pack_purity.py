# -*- coding: utf-8 -*-
"""产物纯净性（A32 精校前移 A2/A3）：混版本、图源对不上，存包时记、标 main 时记进指针。数据自造。"""
from __future__ import annotations

import json

from open_guji_cv.ops import pack_purity as PP
from tests.test_products_diff_pack import FakeSrc


def _st(**steps):
    return {"steps": {sid: {"pages": pages} for sid, pages in steps.items()}}


def test_code_mixed_counts_only_own_code_staleness():
    st = _st(cell_shrink={1: {"status": "stale", "reason": "代码或版本变了"},
                          2: {"status": "stale", "reason": "代码或册配置变了（frame_bar_strategy；旧条目没记册配置原值）"},
                          3: {"status": "fresh"}},
             seed_admit={1: {"status": "stale", "reason": "参数变了：human_fp"},          # 人裁进库：正常过期
                         2: {"status": "stale", "reason": "上游过期", "upstream_stale": True}})
    assert PP.code_mixed(st) == {"cell_shrink": 2}
    assert PP.code_mixed(_st(seed_admit={1: {"status": "fresh"}})) == {}


def _book(tmp_path, rev=3, idx=None):
    d = tmp_path / "vol06"
    d.mkdir(parents=True, exist_ok=True)
    if rev is not None:
        (d / "_source.json").write_text(json.dumps({"book_id": "96mid1ogzk", "vol": "06", "rev": rev}))
    (d / "_raw_index.json").write_text(json.dumps(idx or {"1.png": {"sha256": "a"}, "2.png": {"sha256": "b"}}))
    return d


def test_source_check(tmp_path):
    d = _book(tmp_path)
    table = {"pages": [{"page": 1, "sha256": "a"}, {"page": 2, "sha256": "b"}]}
    assert PP.source_check(d, 3, table)["status"] == "ok"
    assert PP.source_check(d, None, table)["status"] == "unpinned"
    assert PP.source_check(d, 4, table)["status"] == "mismatch"
    bad = PP.source_check(d, 3, {"pages": [{"page": 1, "sha256": "a"}, {"page": 2, "sha256": "x"}]})
    assert bad["status"] == "mismatch" and bad["bad_pages"] == [2]
    assert PP.source_check(_book(tmp_path / "n", rev=None), 3)["status"] == "unknown"
    assert PP.verdict({}, {"status": "unpinned"}) and not PP.verdict({"cell_shrink": 1}, {"status": "ok"})


def test_promote_records_impure_pack(tmp_path, monkeypatch):
    from open_guji_cv.datastore import packs as PK
    monkeypatch.setattr(PK, "_ws_name", lambda: "ws-x")
    root = tmp_path / "products"
    (root / "vol07" / "seed_admit").mkdir(parents=True)
    (root / "vol07" / "seed_admit" / "p0001.json").write_text("A")
    src = FakeSrc()
    vers = {"cv": "0.5.17", "cv_commit": "c" * 40, "corpus": None, "glyph_pin": None, "human_fp": None}
    bad = {"pure": False, "code_mixed": {"cell_shrink": 98}, "source": {"status": "ok"}}
    PK.push_products("vol07", root, label="mix", src=src, vers=vers, purity=bad)
    PK.push_products("vol07", root, label="old", src=src, vers=vers)                 # 老包：没记纯净性
    man = json.loads(src.objs["products/ws-x/vol07/mix/manifest.json"])
    assert man["purity"]["code_mixed"] == {"cell_shrink": 98}
    PK.promote("vol07", "old", src=src)                                               # 老包照旧标，不记
    PK.promote("vol07", "mix", src=src, why="A31 知情：切分步代码只改了注释")          # 不纯：照标，指针里记一笔
    ptr = {k: json.loads(v) for k, v in src.objs.items() if "/main-ptr/" in k}
    mix = next(p for k, p in ptr.items() if k.endswith("-mix.json"))
    old = next(p for k, p in ptr.items() if k.endswith("-old.json"))
    assert mix["impure_why"].startswith("A31") and "cell_shrink 98 页" in mix["impure"] and "impure" not in old
