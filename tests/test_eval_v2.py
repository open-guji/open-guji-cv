# -*- coding: utf-8 -*-
"""P2 收尾：评测器适配层。

重点守两件事（都是实测踩出来的）：
1. **`--out` 有两种冲突语义**：多数脚本是报告路径，char-segmentation 下那批却是
   产物根目录。传错会让脚本扫到 0 页然后印「回归门：通过」——假通过比失败危险。
2. **回归门失败 ≠ 跑挂**：门拦住了东西和门本身坏掉是两回事，混报会让人
   分不清该看算法还是该修评测。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from open_guji_cv.eval.registry import EVALS, EvalSpec, find_eval, runnable
from open_guji_cv.eval.report import EvalReport, Metric, parse_metrics
from open_guji_cv.eval.runner import _gate_verdict

DATASET = Path(__file__).resolve().parent.parent.parent / "open-guji-dataset"
needs_dataset = pytest.mark.skipif(not DATASET.exists(), reason="需要 open-guji-dataset")


# ── 注册表 ───────────────────────────────────────────────────────────
def test_registry_covers_every_eval_script():
    scripts = {p.stem[len("eval_"):] for p in
               (Path(__file__).resolve().parent.parent / "scripts").glob("eval_*.py")}
    missing = scripts - set(EVALS)
    assert not missing, f"这些评测脚本没进注册表: {sorted(missing)}"


def test_out_flag_is_empty_for_product_root_scripts():
    """char-segmentation 下那批的 --out 是产物根目录，绝不能当报告路径传。"""
    product_root = {"char_drop", "left_cut", "right_cut", "page_crop", "text_band",
                    "truncation", "seam", "jiazhu_tail", "side_rule", "crop_margin"}
    for sid in product_root:
        assert EVALS[sid].out_flag == "", f"{sid} 的 --out 是产物根目录，out_flag 必须置空"


def test_update_flag_is_never_passed():
    """--update 会覆写金标 expected.json。"""
    for spec in EVALS.values():
        assert "--update" not in spec.extra
    bad = EvalSpec(id="x", script="eval_x.py", shard="y", extra=("--update",))
    with pytest.raises(AssertionError):
        bad.argv(Path("."))


def test_target_path_kinds(tmp_path):
    ds = tmp_path
    assert EVALS["layout"].target(ds).name == "samples"           # samples 子目录
    assert EVALS["seam"].target(ds) == ds / "char-segmentation"   # 父目录，脚本自己拼
    assert EVALS["pagetype"].target(ds) == ds / "page-type"       # 分片根
    assert EVALS["guard_ceiling"].target(ds) is None              # 没有位置参数


def test_argv_shape(tmp_path):
    argv = EVALS["pagetype"].argv(tmp_path, tmp_path / "r.json")
    assert argv[1].endswith("eval_pagetype.py")
    assert str(tmp_path / "page-type") in argv
    assert "--json-out" in argv                                    # 不是 --out
    # out_flag 为空的不给报告路径
    assert "--out" not in EVALS["seam"].argv(tmp_path, tmp_path / "r.json")


def test_runnable_reports_why():
    ok, why = runnable(EVALS["char_ocr"])
    assert not ok and "引擎" in why
    assert runnable(EVALS["normalize"])[0]


def test_find_eval_by_id_and_shard():
    assert find_eval("pagetype").id == "pagetype"
    assert find_eval("page-type").id == "pagetype"
    assert find_eval("不存在") is None


# ── 回归门解析 ───────────────────────────────────────────────────────
@pytest.mark.parametrize("text,want", [
    ("回归门：通过", "通过"),
    ("回归门：**失败**", "失败"),          # 失败态带星号，通过态不带，不对称
    ("回归门：31/31 通过", "通过"),        # normalize 独有，中间夹分数
    ("回归门: 通过", "通过"),              # 半角冒号
    ("前面通过了\n回归门：失败", "失败"),   # 有失败就是失败
    ("没有门", ""),
])
def test_gate_verdict(text, want):
    assert _gate_verdict(text) == want


# ── 指标解析 ─────────────────────────────────────────────────────────
def test_parse_metrics_shapes():
    m = {x.name: x for x in parse_metrics("缺陷检出率 50%（316 个缺陷）\n标记精确率 82%")}
    assert m["缺陷检出率"].value == 50 and m["缺陷检出率"].denominator == 316
    assert m["标记精确率"].value == 82

    # 行内多字段 + 分层前缀
    m = {x.name: x for x in parse_metrics(
        "all          页  36 列  290  列型准确率  91.4%\n"
        "body         页  12 列  108  列型准确率  99.1%")}
    assert any("91.4" == str(v.value) for v in m.values())
    assert any(k.startswith("body") for k in m)      # 分层不互相覆盖

    # 半角括号的分数百分比
    m = {x.name: x for x in parse_metrics("  残余率（带框组仍有框渣）  0/55 (0%)")}
    assert m["残余率"].value == 0.0 and m["残余率"].denominator == 55

    # 回归门分数
    m = {x.name: x for x in parse_metrics("回归门：31/31 通过")}
    assert m["回归门"].value == 100.0 and m["回归门"].numerator == 31


def test_parse_metrics_skips_per_class_detail():
    """逐类明细行会把 limit 吃光，把真正的总体指标挤掉。"""
    text = ("  body      (切分) n= 294  策略判对  294    100%\n"
            "  toc       (切分) n=  47  策略判对   47    100%\n"
            "网格策略准确率 99.5%（394 页）")
    names = [m.name for m in parse_metrics(text)]
    assert "网格策略准确率" in names


# ── 报告 ─────────────────────────────────────────────────────────────
def test_report_warnings_surface_uncertainty():
    r = EvalReport(eval_id="x", shard="y", metrics=[Metric("acc", 90, denominator=100)])
    assert any("未查金标漂移" in w for w in r.warnings())     # stale_gold 是 None
    r.stale_gold, r.uncertain_skipped = 4, 3
    ws = r.warnings()
    assert any("4 条金标已过期" in w for w in ws)
    assert any("跳过 3 条 uncertain" in w for w in ws)
    r2 = EvalReport(eval_id="x", shard="y", metrics=[Metric("acc", 90)])
    assert any("没有分母" in w for w in r2.warnings())


def test_metric_fmt_carries_denominator():
    assert "（59/65）" in Metric("字保全", 91, numerator=59, denominator=65, unit="%").fmt()
    assert "（n=316）" in Metric("检出", 50, denominator=316, unit="%").fmt()


# ── 真跑 ─────────────────────────────────────────────────────────────
@needs_dataset
def test_run_normalize_for_real():
    """最快的评测器：纯函数 golden，不需要产物。"""
    from open_guji_cv.eval import run_eval
    r = run_eval("normalize", timeout=300)
    assert r.status in ("ok", "regressed"), r.error
    assert r.metrics and r.gate in ("通过", "失败")
    assert r.n_gold == 32                       # char-normalization 32 条
    assert r.stale_gold == 0


@needs_dataset
def test_skipped_eval_reports_reason():
    from open_guji_cv.eval import run_eval
    r = run_eval("char_ocr", timeout=60)
    assert r.status == "skipped" and "引擎" in r.error
