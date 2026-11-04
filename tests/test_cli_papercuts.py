# -*- coding: utf-8 -*-
"""K 引擎卡手五处（卡 #54）几条零碎修复的回归测试：cli_v2.cmd_product /
cmd_check 的具体行为，跟 `core/step.py`、`eval/rulers.py` 那几条更大的
单测分开放，图的是改一条查一条、不用陪跑整条链。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

import pytest

import open_guji_cv.steps  # noqa: F401  注册 v2 步骤与产物种类


# ── K7：`guji cards groups` 曾经 `KeyError: 未注册的产物种类: seed_admit` ──


# ── K20：`guji product raw` 曾经 NameError（缺 import cv_imread）──────────


# ── K9：`guji product patch` 缺缓存时应现场 materialize，不该直接报错退出 ──


# ── K6：`Ruler.to_dict()` 加 `full=True`，做全量错例不再需要 monkeypatch ──
def test_ruler_to_dict_full_flag():
    from open_guji_cv.eval.rulers import Ruler

    r = Ruler("R2", "t", num=1, den=30, detail=[{"i": i} for i in range(30)])
    assert len(r.to_dict()["detail"]) == 20          # 默认仍截断，行为不变
    assert len(r.to_dict(full=True)["detail"]) == 30  # 新开关：不截断


# ── K3：两处裸相对路径改按工作区/GUJI_CACHE_DIR 解析 ──────────────────────
def test_font_candidates_index_dir_follows_cache_root(tmp_path, monkeypatch):
    """`INDEX_DIR = Path("cache/font_index")` 曾是裸相对路径——谁的 cwd 是
    引擎仓根，谁就会真的在仓里写下 `cache/font_index/*.npz`（conftest 的
    `_no_writes_into_the_repo` 就是为这类坑设的）。设了 `GUJI_CACHE_DIR`
    之后，索引必须落在那里，不是仓根。"""
    from open_guji_cv.clustering import font_candidates as fc

    cache_dir = tmp_path / "mycache"
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache_dir))
    mat, keys = fc._index(("一",))
    assert (cache_dir / "font_index").is_dir()
    assert list((cache_dir / "font_index").glob("*.npz")), "索引没有落进 GUJI_CACHE_DIR"
    assert mat.shape[0] == len(keys)


def test_general_lm_cache_follows_cache_root_not_corpus_dir(tmp_path, monkeypatch):
    """`_load_general_lm` 曾把缓存落在 `paths[0].parent`（语料文件旁边）——
    语料若解析到仓内 `corpus/external/`，缓存就跟着写进仓里。改成落
    `cache_root()/general_lm/`，与语料目录彻底脱钩。"""
    from open_guji_cv.clustering.seeding import _load_general_lm

    corpus_dir = tmp_path / "somewhere_far_away" / "corpus_like_dir"
    corpus_dir.mkdir(parents=True)
    p = corpus_dir / "a.txt"
    p.write_text("云雨江湖" * 50, encoding="utf-8")

    cache_dir = tmp_path / "mycache"
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache_dir))
    _load_general_lm([p])
    assert not list(corpus_dir.glob("*.json")), "缓存不该写进语料目录"
    assert list((cache_dir / "general_lm").glob("general-*.json"))


# ── K21：`context_decide`(step_id) 与 `context_decision`(kind_id) 不同名，
#     按 kind_id 误当 step_id 查会静默 0 条 ─────────────────────────────
def test_resolve_step_id_corrects_kind_id_confusion():
    from open_guji_cv.core.step import resolve_step_id

    assert resolve_step_id("context_decide") == "context_decide"      # 本来就是 step_id，原样返回
    assert resolve_step_id("context_decision") == "context_decide"    # kind_id → 解到产出它的 step_id
    with pytest.raises(KeyError, match="既不是已知的 step_id"):
        resolve_step_id("这不是任何东西")


# ── K2：`round_check.load_verdicts()` 缺省先认工作区，不再直落 DATASET ────


# ── K13：`glyph-db` 认 `-w`，没有工作区时报错退出（不再静默写进 cv 仓 output/） ──


# ── K15：`eval_frame_residue.py --pages all` 的 max_page 硬编码 300 改按书实际页数 ──
def test_eval_frame_residue_max_page_follows_book_not_hardcoded_300(repo_root):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "eval_frame_residue_k15", repo_root / "scripts" / "eval_frame_residue.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from pathlib import Path as _P
    from open_guji_cv.core.book import BookSpec

    big_book = BookSpec(id="qtw", title="全唐文", raw_dir=_P("does-not-matter"),
                        pages=list(range(1, 401)))   # 401 页，超过硬编码的 300
    assert mod._expand_pages("all", max(big_book.all_pages())) == list(range(1, 401)), \
        "改前：max_page 恒为 300，--pages all 会漏掉 301-400"


# ── K10：`status`／`collate` 缺 -w 时认 GUJI_WORKSPACE（其余命令仍必须显式 -w） ──
def test_resolve_workspace_status_falls_back_to_env(tmp_path, monkeypatch, capsys):
    from open_guji_cv import cli_v2
    import argparse as _ap

    ws = tmp_path / "ws"
    (ws / "books").mkdir(parents=True)
    (ws / "books" / "vol01.yaml").write_text("id: vol01\n", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))

    parser = _ap.ArgumentParser()
    args = _ap.Namespace(book="vol01", workspace=None)
    root = cli_v2.resolve_workspace(args, parser, command="status")
    assert root == ws.resolve()
    assert "退回 GUJI_WORKSPACE" in capsys.readouterr().err


# ── K11：quality()／round_check.accuracy() 比对前按书级 codepoints 归一 ──


def test_resolve_workspace_pipeline_still_requires_dash_w(tmp_path, monkeypatch):
    """不在 `ENV_FALLBACK_COMMANDS` 里的命令（如 pipeline/step）不受影响——
    2026-09-19 定的『不再读 GUJI_WORKSPACE 兜底』规矩原样保留，这条防它被
    K10 的改动悄悄放松。"""
    from open_guji_cv import cli_v2
    import argparse as _ap

    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    parser = _ap.ArgumentParser(prog="test")
    args = _ap.Namespace(book="vol01", workspace=None)
    with pytest.raises(SystemExit):
        cli_v2.resolve_workspace(args, parser, command="pipeline")

