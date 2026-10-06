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
def test_group_view_module_registers_seed_admit_kind_standalone():
    """`review/group_view.py` 读 `seed_admit` 产物前没 import
    `products.kinds`（那才是真正注册 `ProductKindSpec` 的地方），只要进程里
    还没有别的模块先注册过，`st.read(book, "seed_admit", …)` 就会
    `KeyError: 未注册的产物种类: seed_admit`。这条在**干净子进程**里跑，
    不然 pytest 一个进程导入几十个测试文件，早被别人注册过，测不出回归。"""
    code = (
        "import open_guji_cv.review.group_view\n"
        "from open_guji_cv.core.step import KINDS\n"
        "assert 'seed_admit' in KINDS, KINDS.keys()\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ── K20：`guji product raw` 曾经 NameError（缺 import cv_imread）──────────
def test_cmd_product_raw_no_nameerror(tmp_path, ws, capsys):
    """2026-09-27 起 `cmd_product` action=raw 分支直接崩 `NameError:
    name 'cv_imread' is not defined`（局部 import 只带了 cv2，没带
    `utils.image_io.imread as cv_imread`）。跑一次真页确认不再崩、且真的
    编出了 PNG。"""
    from open_guji_cv.cli_v2 import cmd_product

    out = tmp_path / "raw.png"
    args = argparse.Namespace(action="raw", book="keben", step="", page=1,
                              key="", col=0, slot=0, sub="", scale=0.35, out=str(out))
    cmd_product(args)
    assert out.exists() and out.stat().st_size > 0
    capsys.readouterr()


# ── K9：`guji product patch` 缺缓存时应现场 materialize，不该直接报错退出 ──
def test_cmd_product_patch_materializes_on_cache_miss(tmp_path, monkeypatch, ws, capsys):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import load_pipeline
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.cli_v2 import cmd_product

    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "products"))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    pl = load_pipeline("keben_body_v2")
    book = load_book("keben")
    store, cache = ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")
    eng = Engine(book, pl, store=store, cache=cache, log=lambda s: None)
    rep = eng.run(steps=["border_detect", "column_warp", "row_segment", "cell_shrink"],
                  pages=[1])
    assert not rep.to_dict()["failed"], rep.to_dict()["failed"]

    chars = store.read(book.id, "cell_shrink", "p0001", "char_index")
    col, ch = next((c, r) for c in chars.columns for r in c.chars if r.patch_key)
    key = ch.patch_key
    cache_path = cache.path(book.id, "char_patch", key)
    assert cache_path.exists()
    cache_path.unlink()   # 模拟「拿了快照，products/ 有、cache/ 没有」

    out = tmp_path / "patch.png"
    args = argparse.Namespace(action="patch", book="keben", step="", page=1, key="",
                              col=col.col, slot=ch.slot, sub=(ch.sub or ""), scale=0.35,
                              out=str(out))
    cmd_product(args)   # 之前这里会直接 print("没有字块 …") 后 sys.exit(1)
    assert out.exists() and out.stat().st_size > 0
    capsys.readouterr()


def test_cmd_product_patch_still_errors_when_materialize_cant(tmp_path, ws, capsys):
    """真的没有这个格（page/col/slot 瞎编）时，materialize 也补不出来，
    仍然要清楚报错退出，不能吞掉异常裸崩。"""
    from open_guji_cv.cli_v2 import cmd_product

    args = argparse.Namespace(action="patch", book="keben", step="", page=1, key="",
                              col=99, slot=99, sub="", scale=0.35, out=str(tmp_path / "x.png"))
    with pytest.raises(SystemExit):
        cmd_product(args)
    err = capsys.readouterr().out
    assert "没有字块" in err


# ── K1：`guji check quality`／`check rulers` 默认页集改 all，且总要打印用的是哪个页集 ──
def test_check_pages_default_is_all_and_reports_which_pageset(monkeypatch, capsys):
    """`--pages` 缺省曾经是 `dev_set`：书级 `dev_set` 为空时悄悄退化成全书
    （凑巧对），非空时悄悄只算子集、不报警。改成默认 `all`；且不论默不默认，
    都要把「用了哪个页集、算了几页」打出来（走 stderr，别混进 `_out` 的
    JSON，管道接 jq 的人不受影响）。"""
    import open_guji_cv.core.book as book_mod
    import open_guji_cv.eval.quality as quality_mod
    import open_guji_cv.eval.rulers as rulers_mod
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv import cli_v2

    from pathlib import Path as _P
    fake = BookSpec(id="fakebook", title="t", raw_dir=_P("does-not-matter"),
                    pages=[1, 2, 3], dev_set=[1])   # 非空 dev_set：旧默认会悄悄只算这一页
    # cmd_check 是函数内局部 import（`from .core.book import load_book` 等），
    # 每次调用都现从源模块取绑定，所以补丁要打在源模块上，不是 cli_v2 模块本身。
    monkeypatch.setattr(book_mod, "load_book", lambda *_a, **_k: fake)
    monkeypatch.setattr(quality_mod, "quality",
                        lambda book, pages, store: {"book": book, "pages": len(fake.resolve_pages(pages))})
    monkeypatch.setattr(rulers_mod, "measure",
                        lambda book, pages, store, full=False:
                            {"book": book, "n_pages": len(pages), "rulers": [], "full": full})

    args = argparse.Namespace(action="quality", book="fakebook", pages=None,
                              snapshot=False, note="", all_pages=False, full=False,
                              drift=False, out="")
    cli_v2.cmd_check(args)
    out, err = capsys.readouterr()
    assert json.loads(out)["pages"] == len(fake.all_pages())   # all，不是 dev_set 的 1 页
    assert "all" in err and "页" in err

    args2 = argparse.Namespace(action="rulers", book="fakebook", pages=None,
                               snapshot=False, note="", all_pages=False, full=False,
                               drift=False, out="")
    cli_v2.cmd_check(args2)
    out2, err2 = capsys.readouterr()
    assert json.loads(out2)["n_pages"] == len(fake.all_pages())
    assert "all" in err2 and "页" in err2


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
    assert not (corpus_dir / ".general_lm_cache.json").exists(), "缓存不该写进语料目录"
    assert (cache_dir / "general_lm" / ".general_lm_cache.json").exists()


# ── K21：`context_decide`(step_id) 与 `context_decision`(kind_id) 不同名，
#     按 kind_id 误当 step_id 查会静默 0 条 ─────────────────────────────
def test_resolve_step_id_corrects_kind_id_confusion():
    from open_guji_cv.core.step import resolve_step_id

    assert resolve_step_id("context_decide") == "context_decide"      # 本来就是 step_id，原样返回
    assert resolve_step_id("context_decision") == "context_decide"    # kind_id → 解到产出它的 step_id
    with pytest.raises(KeyError, match="既不是已知的 step_id"):
        resolve_step_id("这不是任何东西")


def test_cmd_product_manifest_autocorrects_kind_id_and_warns(tmp_path, monkeypatch, ws, capsys):
    """`guji product manifest <book> context_decision` 曾经悄悄查到空
    manifest（`context_decide` 才是真正的目录名）。现在要自动纠正并在
    stderr 提示，而不是让人以为『这本书还没有 Step6 产物』。"""
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import load_pipeline
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.steps.align_ref import AlignRefParams
    from open_guji_cv.steps.context_decide import ContextDecideParams
    from open_guji_cv.cli_v2 import cmd_product
    import argparse

    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "products"))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    pl = load_pipeline("keben_body_v2")
    book = load_book("keben")
    store, cache = ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")
    eng = Engine(book, pl, store=store, cache=cache, log=lambda s: None)
    corpus = ws / "corpus" / "reference.txt"
    eng.ctx.params["align_ref"] = AlignRefParams(corpus=str(corpus))
    eng.ctx.params["context_decide"] = ContextDecideParams(
        corpus=str(corpus), general_corpus_dir=str(tmp_path / "no_general_corpus"))
    # 只跑 context_decide 真正硬依赖的那几步（`consumes=("glyph_match",)`）——
    # 不带 rare_candidates/ocr_candidates/align_ref：一装了 torch，rare_candidates
    # 就会去建「unicode-cjk-a」那张几万字的 CNN embedding 索引，几分钟起步，
    # 这条用例只想测 CLI 的 kind_id/step_id 纠错，不该陪跑那条冷启动。
    rep = eng.run(steps=["border_detect", "column_warp", "row_segment", "cell_shrink",
                        "glyph_match", "context_decide"], pages=[1])
    assert not rep.to_dict()["failed"], rep.to_dict()["failed"]

    args = argparse.Namespace(action="manifest", book="keben", step="context_decision",
                              key="", page=0, col=0, slot=0, sub="", scale=0.35, out="")
    cmd_product(args)
    out, err = capsys.readouterr()
    assert json.loads(out), "自动纠正后应该读到 context_decide 目录下真有的产物"
    assert "context_decide" in err and "kind_id" in err


# ── K2：`round_check.load_verdicts()` 缺省先认工作区，不再直落 DATASET ────
def test_load_verdicts_prefers_workspace_events(tmp_path, monkeypatch, capsys):
    from open_guji_cv.eval import round_check as rc

    ws_events = tmp_path / "ws" / "feedback" / "events"
    ws_events.mkdir(parents=True)
    dataset_events = tmp_path / "dataset" / "feedback" / "events"
    dataset_events.mkdir(parents=True)
    monkeypatch.setattr(rc, "DATASET", tmp_path / "dataset")

    import json as _json
    ev = {"actor": "user", "kind": "confirm", "target": {"key": "vol01:1:1:1"},
         "payload": {"v": "confirm", "shape": "從工作区"}, "ts": "2026-09-27T00:00:00"}
    (ws_events / "vol01-dev_set-decide.jsonl").write_text(_json.dumps(ev, ensure_ascii=False) + "\n",
                                                          encoding="utf-8")
    # DATASET 里放一份不同的裁决——用来证明真读到的是工作区那份，不是 DATASET
    ev_dataset = dict(ev, payload={"v": "confirm", "shape": "從dataset"})
    (dataset_events / "vol01-dev_set-decide.jsonl").write_text(
        _json.dumps(ev_dataset, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "ws"))
    out = rc.load_verdicts("vol01")
    assert out == {"vol01:1:1:1": "從工作区"}
    capsys.readouterr()


def test_load_verdicts_reads_cross_book_batch_files(tmp_path, monkeypatch, capsys):
    """全唐文人裁在跨册批次文件 `qtw-human-batch*.jsonl` 里（C #166 查出）：
    文件名不以书 id 开头也要读到，按 target.key 的书前缀过滤，别册的不混进来。"""
    from open_guji_cv.eval import round_check as rc
    import json as _json

    ws_events = tmp_path / "ws" / "feedback" / "events"
    ws_events.mkdir(parents=True)
    monkeypatch.setattr(rc, "DATASET", tmp_path / "dataset")
    rows = [
        {"actor": "user", "kind": "confirm", "target": {"key": "v007:3:1:2"},
         "payload": {"v": "confirm", "shape": "聞"}, "ts": "2026-09-27T01:00:00"},
        {"actor": "user", "kind": "confirm", "target": {"key": "v2:v007:3:1:3"},
         "payload": {"v": "confirm", "shape": "爲"}, "ts": "2026-09-27T01:00:01"},
        {"actor": "user", "kind": "confirm", "target": {"key": "v0070:3:1:2"},
         "payload": {"v": "confirm", "shape": "別册"}, "ts": "2026-09-27T01:00:02"},
        {"actor": "user", "kind": "confirm", "target": {"key": "v008:3:1:2"},
         "payload": {"v": "confirm", "shape": "他册"}, "ts": "2026-09-27T01:00:03"},
    ]
    (ws_events / "qtw-human-batch1.jsonl").write_text(
        "".join(_json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "ws"))
    assert rc.load_verdicts("v007") == {"v007:3:1:2": "聞", "v2:v007:3:1:3": "爲"}
    capsys.readouterr()


def test_load_verdicts_falls_back_to_dataset_and_warns_when_both_empty(tmp_path, monkeypatch, capsys):
    from open_guji_cv.eval import round_check as rc

    monkeypatch.setattr(rc, "DATASET", tmp_path / "dataset")   # 不存在，天然空
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "empty_ws"))  # 也不存在
    out = rc.load_verdicts("vol99")
    assert out == {}
    err = capsys.readouterr().err
    assert "vol99" in err and "0 条" in err   # 不许悄悄回空字典不说话


def test_load_verdicts_explicit_root_still_works(tmp_path, monkeypatch):
    """显式传 `root`（老调用点如 `research/metric_loss/*.py` 传的是工作区根，
    不是 events 目录本身）行为不变：函数自己拼 `feedback/events`。"""
    from open_guji_cv.eval import round_check as rc
    import json as _json

    root = tmp_path / "explicit_ws"       # 一个「工作区根」，不是 events 目录
    (root / "feedback" / "events").mkdir(parents=True)
    ev = {"actor": "user", "kind": "confirm", "target": {"key": "vol01:1:1:1"},
         "payload": {"v": "confirm", "shape": "甲"}, "ts": "t"}
    (root / "feedback" / "events" / "vol01-x-decide.jsonl").write_text(
        _json.dumps(ev, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path / "should_be_ignored"))
    assert rc.load_verdicts("vol01", root=root) == {"vol01:1:1:1": "甲"}


# ── K13：`glyph-db` 认 `-w`，没有工作区时报错退出（不再静默写进 cv 仓 output/） ──
def test_glyph_db_requires_workspace_or_explicit_sample_db_opt_in():
    from open_guji_cv.__main__ import cmd_glyph_db

    args = argparse.Namespace(action="stats", workspace=None, allow_sample_db=False,
                              store=None, no_others=False, apply=False, path=None,
                              edition=None, manifest="config/fonts/manifest.json",
                              vertical=False, charset=None, limit=None, jobs=1,
                              collection=None, script_style=None, title=None)
    with pytest.raises(RuntimeError, match="没设 GUJI_WORKSPACE"):
        cmd_glyph_db(args)


def test_glyph_db_dash_w_overrides_and_is_respected(tmp_path, monkeypatch):
    """`-w` 传了之后要真的落到 `GUJI_WORKSPACE`，`glyph_db_path()` 按它解析
    ——以前这个命令只认环境变量，`-w` 传了也没用。"""
    from open_guji_cv.__main__ import cmd_glyph_db
    from open_guji_cv.core.workspace import glyph_db_path

    monkeypatch.delenv("GUJI_WORKSPACE", raising=False)
    ws = tmp_path / "myws"
    ws.mkdir()
    args = argparse.Namespace(action="stats", workspace=str(ws), allow_sample_db=False,
                              store=None, no_others=False, apply=False, path=None,
                              edition=None, manifest="config/fonts/manifest.json",
                              vertical=False, charset=None, limit=None, jobs=1,
                              collection=None, script_style=None, title=None)
    cmd_glyph_db(args)
    assert glyph_db_path() == (ws / "output" / "glyph.db").resolve()


def test_glyph_db_allow_sample_db_opt_in_does_not_error(tmp_path, monkeypatch, capsys):
    from open_guji_cv.__main__ import cmd_glyph_db

    monkeypatch.delenv("GUJI_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)   # 别真的碰 cv 仓自己的 output/
    args = argparse.Namespace(action="stats", workspace=None, allow_sample_db=True,
                              store=None, no_others=False, apply=False, path=None,
                              edition=None, manifest="config/fonts/manifest.json",
                              vertical=False, charset=None, limit=None, jobs=1,
                              collection=None, script_style=None, title=None)
    cmd_glyph_db(args)   # 不该抛
    capsys.readouterr()


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
def test_quality_treats_book_codepoints_pair_as_match(tmp_path, monkeypatch):
    """內/内 这类本书 `codepoints:` 统一过的对，pred 与整理本金标字面不同，
    但按书级码位算是同一个字——不该被 quality() 记成「与整理本不一致」。"""
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv.core import book as book_mod
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.eval import quality as quality_mod
    from open_guji_cv.gold import v2_align as v2_align_mod
    from open_guji_cv.gold.v2_align import GoldChar, PageGold
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
    from open_guji_cv.products.store import ProductStore

    book_id = "k11book"
    fake_book = BookSpec(id=book_id, title="t", raw_dir=tmp_path,
                         codepoints={"内": "內"})   # 本书统一到「內」
    monkeypatch.setattr(book_mod, "load_book", lambda *_a, **_k: fake_book)

    cid = f"{book_id}:1:1:1"
    monkeypatch.setattr(v2_align_mod, "align_book", lambda *_a, **_k: [
        PageGold(book=book_id, page=1, anchored=True, n_chars=1,
                chars=[GoldChar(id=cid, page=1, col=1, slot=1, shape="内", ref="內",
                                align_op="equal")])])

    store = ProductStore(tmp_path / "products")
    store.write(book_id, "seed_admit", page_key(1), {
        "seed_admit": PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[
            AdmitRec(id=cid, slot=1, admit=True, char="内", channel="match_solo")])])})

    out = quality_mod.quality(book_id, [1], store)
    assert out["accuracy"]["n_gold"] == 1
    assert out["accuracy"]["overall"] == 1.0, out["accuracy"]["errors"]


def test_round_check_accuracy_treats_book_codepoints_pair_as_match(tmp_path, monkeypatch):
    from open_guji_cv.core.book import BookSpec
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.core import book as book_mod
    from open_guji_cv.eval import round_check as rc
    from open_guji_cv.gold import v2_align as v2_align_mod
    from open_guji_cv.gold.v2_align import GoldChar, PageGold
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
    from open_guji_cv.products.store import ProductStore

    book_id = "k11book2"
    fake_book = BookSpec(id=book_id, title="t", raw_dir=tmp_path,
                         codepoints={"内": "內"})
    monkeypatch.setattr(book_mod, "load_book", lambda *_a, **_k: fake_book)

    cid = f"{book_id}:1:1:1"
    monkeypatch.setattr(v2_align_mod, "align_book", lambda *_a, **_k: [
        PageGold(book=book_id, page=1, anchored=True, n_chars=1,
                chars=[GoldChar(id=cid, page=1, col=1, slot=1, shape="内", ref="內",
                                align_op="equal")])])
    monkeypatch.setattr(rc, "load_verdicts", lambda *_a, **_k: {})

    store = ProductStore(tmp_path / "products")
    store.write(book_id, "seed_admit", page_key(1), {
        "seed_admit": PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[
            AdmitRec(id=cid, slot=1, admit=True, char="内", channel="match_solo")])])})

    out = rc.accuracy(book_id, [1], store)
    assert out["gold"] == [1, 1], out["errors"]


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

