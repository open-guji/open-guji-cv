# -*- coding: utf-8 -*-
"""scripts/zhengli/pending_list.py（GUJI-652 从 ai-team 迁入）：自造 seed_admit 产物，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "pending_list.py"
spec = importlib.util.spec_from_file_location("zhengli_pending_list", SCRIPT)
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


def make_products(tmp_path: Path, n_review: int = 2) -> Path:
    """一页 seed_admit：放行 1 格、待审 2 格（含带 sub 的）、排除名单 1 格。"""
    seed = tmp_path / "products" / "vol01" / "seed_admit"
    seed.mkdir(parents=True)
    doc = {"seed_admit": {"n_review": n_review, "columns": [
        {"chars": [
            {"id": "vol01:1:1:1", "admit": True},
            {"id": "vol01:1:1:2", "admit": False, "doubts": ["lib_miss"]},
            {"id": "vol01:1:1:3", "admit": False, "doubts": ["excluded"],
             "evidence": {"excluded": "human:seg_defect"}},
        ]},
        {"chars": [{"id": "vol01:1:2:1a", "admit": False}]},
    ]}}
    (seed / "p0001.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path / "products"


def base_args(products: Path, out: Path, rev: str = "vol01-r0") -> list[str]:
    return ["--products", str(products), "--book", "vol01", "--chapter", "001",
            "--rev", rev, "--cv-commit", "abc1234", "--out", str(out)]


def test_plain_pending_lists_unadmitted_non_excluded_cells(tmp_path):
    out = tmp_path / "out"
    pl.main(base_args(make_products(tmp_path), out))
    doc = json.loads((out / "001.pending.json").read_text(encoding="utf-8"))
    assert doc == {"rev": "vol01-r0", "cv_version": None, "cv_commit": "abc1234",
                   "cells": [{"cell": "1:1:2", "review": "pending"},
                             {"cell": "1:2:1a", "review": "pending"}]}


def test_chapter_style_rev_is_accepted(tmp_path):
    out = tmp_path / "out"
    pl.main(base_args(make_products(tmp_path), out, rev="001-r2"))
    assert json.loads((out / "001.pending.json").read_text(encoding="utf-8"))["rev"] == "001-r2"


def test_bad_rev_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        pl.main(base_args(make_products(tmp_path), tmp_path / "out", rev="vol02-r1"))
    assert "rev=" in str(e.value.code)


def test_n_review_mismatch_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        pl.main(base_args(make_products(tmp_path, n_review=5), tmp_path / "out"))
    assert "格数不符" in str(e.value.code)


def test_missing_seed_dir_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        pl.main(base_args(tmp_path / "nope", tmp_path / "out"))
    assert "没有" in str(e.value.code)


def test_review_queue_adds_extra_cells_after_products(tmp_path):
    q = tmp_path / "queue.txt"
    q.write_text("vol01:1:1:2\n1:2:1a  # 注释\n\n1:3:4\nvol01:1:3:4\n", encoding="utf-8")
    out = tmp_path / "out"
    pl.main(base_args(make_products(tmp_path), out) + ["--review-queue", str(q)])
    cells = json.loads((out / "001.pending.json").read_text(encoding="utf-8"))["cells"]
    assert [c["cell"] for c in cells] == ["1:1:2", "1:2:1a", "1:3:4"]


def test_review_queue_missing_product_cell_exits(tmp_path):
    q = tmp_path / "queue.txt"
    q.write_text("1:1:2\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        pl.main(base_args(make_products(tmp_path), tmp_path / "out") + ["--review-queue", str(q)])
    assert "不在审卡队列" in str(e.value.code)


def test_cards_merge_proof_fields_with_default_cv_root(tmp_path):
    cards = [
        {"id": "vol01:1:1:2", "cls": "lib_miss", "doubts": [],
         "db": {"candidates": [["之", 0.91234], ["乏", 0.5]], "verdict": "review", "cov": 0.8, "wmax": 3.0},
         "ref": {"char": "之", "op": "equal"}},
        {"id": "vol01:1:2:1a", "alt": [{"c": "乎", "s": 0.7, "p": "之", "src": "v"}]},
    ]
    cf = tmp_path / "cards.json"
    cf.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    pl.main(base_args(make_products(tmp_path), out) + ["--cards", str(cf)])   # 不给 --cv-root：用本仓
    cells = json.loads((out / "001.pending.json").read_text(encoding="utf-8"))["cells"]
    a, b = cells
    assert a["cell"] == "1:1:2" and a["review"] == "pending"
    assert "cls" not in a and a["why"] == ["none"]              # 11-04 起卡片类别不出单
    assert a["lib_top"] == [{"c": "之", "s": 0.9123}, {"c": "乏", "s": 0.5}]
    assert a["ref"] == {"c": "之", "op": "equal"}
    assert b["alt"] == [{"c": "乎", "s": 0.7, "p": "之", "src": "v"}]


def test_cards_missing_a_pending_cell_exits(tmp_path):
    cf = tmp_path / "cards.json"
    cf.write_text(json.dumps([{"id": "vol01:1:1:2"}]), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        pl.main(base_args(make_products(tmp_path), tmp_path / "out") + ["--cards", str(cf)])
    assert "找不到" in str(e.value.code)


def test_cv_root_without_cards_exits(tmp_path):
    with pytest.raises(SystemExit):
        pl.main(base_args(make_products(tmp_path), tmp_path / "out") + ["--cv-root", str(tmp_path)])


def test_ws_text_id_writes_under_data_home(tmp_path, monkeypatch):
    home = tmp_path / "data-home"
    monkeypatch.setenv("GUJI_DATA_HOME", str(home))
    args = base_args(make_products(tmp_path), tmp_path / "out")
    args = args[:-2] + ["--ws", "my-ws", "--text-id", "96mid1ogzk"]
    pl.main(args)
    assert (home / "main" / "my-ws" / "feedback" / "lists" / "proofing" / "96mid1ogzk" / "001.pending.json").is_file()


def test_out_and_ws_are_exclusive(tmp_path):
    args = base_args(make_products(tmp_path), tmp_path / "out") + ["--ws", "w", "--text-id", "abcd"]
    with pytest.raises(SystemExit):
        pl.main(args)


def test_cell_key_orders_numerically():
    assert pl.cell_key("1:10:2a") > pl.cell_key("1:9:3")


def test_recheck_puts_cells_back_with_note_and_prior(tmp_path):
    """--recheck：已放行的格也放回单上，带 recheck／note／prior；现行切分里没有的记进 recheck_missing.tsv。"""
    out = tmp_path / "out"
    rc = tmp_path / "recheck.tsv"
    rc.write_text("格位\t说明\t旧人裁\t旧人裁的字\t旧人裁时间\n"
                  "vol01:1:1:1\t旧裁 山，新票 由，请定\tev9\t山\t2026-10-22T08:45:00Z\n"
                  "1:1:2\t几票不一致\n"
                  "9:9:9\t切字改过\n", encoding="utf-8")
    pl.main(base_args(make_products(tmp_path), out) + ["--recheck", str(rc)])
    doc = json.loads((out / "001.pending.json").read_text(encoding="utf-8"))
    by = {c["cell"]: c for c in doc["cells"]}
    assert [c["cell"] for c in doc["cells"]] == ["1:1:1", "1:1:2", "1:2:1a"]
    assert by["1:1:1"] == {"cell": "1:1:1", "review": "pending", "recheck": True, "note": "旧裁 山，新票 由，请定",
                           "prior": {"c": "山", "id": "ev9", "ts": "2026-10-22T08:45:00Z"}}
    assert by["1:1:2"]["recheck"] is True and by["1:1:2"]["note"] == "几票不一致" and "prior" not in by["1:1:2"]
    assert "recheck" not in by["1:2:1a"]
    assert (out / "recheck_missing.tsv").read_text(encoding="utf-8").splitlines()[1:] == ["9:9:9\t切字改过"]


#: 自造产物没有 cell_shrink 目录：manager meta_fresh 看到的现行页集是空的，meta 记空才算新鲜
_FRESH = {"seed_admit": {}, "cell_shrink": {}}


def _flags(tmp_path: Path, rows: list[tuple], meta: dict | None = None) -> Path:
    f = tmp_path / "seg_selfcheck.tsv"
    head = "格号\tseg_kind\t特征\t放行\t通道\t机器字\t整理本字\t字块键\n"
    f.write_text(head + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    if meta is not None:
        f.with_name(f.name + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return f


def test_seg_flags_adds_admitted_clipped_and_tags_pending(tmp_path):
    """同字对照自检（B1③）：已放行、clipped 的格加进单子（why seg_defect、src seg_selfcheck）；已在单上的只加旗；
    frame_residue 不在送审类别里、只记旗；人裁通道的格不动。"""
    prod = make_products(tmp_path)
    seed = prod / "vol01" / "seed_admit" / "p0001.json"
    doc = json.loads(seed.read_text(encoding="utf-8"))
    doc["seed_admit"]["columns"][0]["chars"] += [{"id": "vol01:1:1:4", "admit": True}, {"id": "vol01:1:1:5", "admit": True}]
    seed.write_text(json.dumps(doc), encoding="utf-8")
    f = _flags(tmp_path, [
        ("vol01:1:1:1", "clipped", "同字墨高 0.70 宽 1.00（参照 9 个） 边线压墨 0.00", "是", "match_ref", "甲", "甲", "p0001c01s1"),
        ("1:1:2", "frame_residue", "同字墨宽 1.2", "否", "", "", "", "p0001c01s2"),
        ("1:1:4", "frame_residue", "同字墨宽 1.2", "是", "match_ref", "乙", "乙", "p0001c01s4"),
        ("1:1:5", "clipped", "同字墨高 0.7", "是", "human", "丙", "丙", "p0001c01s5"),
    ], meta={"review_kinds": ["clipped"], "products": _FRESH})
    out = tmp_path / "out"
    pl.main(base_args(prod, out) + ["--seg-flags", str(f)])
    cells = {c["cell"]: c for c in json.loads((out / "001.pending.json").read_text(encoding="utf-8"))["cells"]}
    assert sorted(cells) == ["1:1:1", "1:1:2", "1:2:1a"]
    assert cells["1:1:1"]["src"] == "seg_selfcheck" and cells["1:1:1"]["why"] == ["seg_defect"]
    assert cells["1:1:1"]["seg_kind"] == "clipped" and cells["1:1:1"]["seg_feature"].startswith("同字")
    assert cells["1:1:2"]["selfcheck_kind"] == "frame_residue" and "seg_kind" not in cells["1:1:2"]
    assert "src" not in cells["1:1:2"] and "why" not in cells["1:1:2"]


def test_seg_flags_stale_or_missing_meta_exits(tmp_path):
    """旗表过期（meta 记的页和指纹对不上现行产物）或没有 .meta.json：退出，不悄悄照收。"""
    prod = make_products(tmp_path)
    f = _flags(tmp_path, [], meta={"products": {"seed_admit": {"p0001": "0" * 64}, "cell_shrink": {}}})
    with pytest.raises(SystemExit, match="过期"):
        pl.main(base_args(prod, tmp_path / "out") + ["--seg-flags", str(f)])
    f = _flags(tmp_path, [], meta={"review_kinds": ["clipped"]})          # 没记指纹
    with pytest.raises(SystemExit, match="过期"):
        pl.main(base_args(prod, tmp_path / "out") + ["--seg-flags", str(f)])
    f.with_name(f.name + ".meta.json").unlink()
    with pytest.raises(SystemExit, match="meta"):
        pl.main(base_args(prod, tmp_path / "out") + ["--seg-flags", str(f)])
    f = _flags(tmp_path, [], meta={"products": _FRESH})
    pl.main(base_args(prod, tmp_path / "out") + ["--seg-flags", str(f)])


def test_seg_flags_keep_existing_seg_kind_detail(tmp_path):
    """已在单上、原因 seg_defect／jiazhu_uneven 的格被同字对照标了 clipped：只加 selfcheck_kind，detail 不变（A20 审 #1089）。"""
    from guji_manager.review.pending_reason import PendingReason as R
    from guji_manager.review.reasons import reasons_for_pending
    prod = make_products(tmp_path)
    f = _flags(tmp_path, [("1:1:2", "clipped", "同字墨高 0.7", "否", "", "", "", "p0001c01s2")], meta={"products": _FRESH})
    out = tmp_path / "out"
    pl.main(base_args(prod, out) + ["--seg-flags", str(f)])
    doc = json.loads((out / "001.pending.json").read_text(encoding="utf-8"))
    c = next(x for x in doc["cells"] if x["cell"] == "1:1:2")
    assert c["selfcheck_kind"] == "clipped" and "seg_kind" not in c
    c["why"] = ["jiazhu_uneven"]                       # 原来就是夹注两行分法不均
    res = reasons_for_pending(doc, tmp_path / "noprod", "vol01", are_variants=lambda a, b: False)
    assert res["1:1:2"] == (R.SEG_DEFECT, "jiazhu_uneven")


def test_gate_excluded_unseen_cell_is_pending(tmp_path):
    """排除名单上没人看过的格（gate:crop_defect）上单；有人给字的 gate 格、human:* 的格不上。页头 n_review 不计它们。"""
    seed = tmp_path / "products" / "vol01" / "seed_admit"
    seed.mkdir(parents=True)
    ex = lambda cid, why, **ev: {"id": cid, "admit": False, "doubts": ["excluded"], "evidence": {"excluded": why, **ev}}
    doc = {"seed_admit": {"n_review": 0, "columns": [{"chars": [
        ex("vol01:1:1:1", "gate:crop_defect"),
        ex("vol01:1:1:2", "gate:crop_defect", human_char="字"),
        ex("vol01:1:1:3", "human:crop_defect"),
        ex("vol01:1:1:4", "human:damaged", damaged=True),
    ]}]}}
    (seed / "p0001.json").write_text(json.dumps(doc), encoding="utf-8")
    cells, n = pl.pending_cells(seed, "vol01")
    assert [c["cell"] for c in cells] == ["1:1:1"] and n == 1
