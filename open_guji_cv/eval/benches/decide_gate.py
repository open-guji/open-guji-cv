"""decide-gate：decide_gate（第四步出口 gate，只检测不改格）的检出率与误报率（CV4，接统一接口）。

做法：先按 decide 的冻结层跑一遍收尾（`decide_bench/run.py`，关人裁），再让 `decide_bench/gate_bench.py` 对产物
逐格检测，数「放错字格被 fail 标出」的比例（检出率）和「放对格被 fail 标出」的比例（误报率）。
资源与 decide 相同；参数 `--arg set=small|large`。主指标 `detect_rate`；护栏 `false_alarm_rate` 不超过 0.5%（11-28 基线 0.24%）。
注意：现行金标里放错字很少（殿本 small 1 格），检出率分母小；事故回归例（殿本 12 格）在 ai-team 基线报告里，尚未进 dataset。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register
from . import decide as D


def run(ctx: BenchCtx) -> Path:
    if ctx.args.get("layer", "frozen") != "frozen":
        raise ValueError("decide-gate 只跑 frozen 层")
    pred = D.run(ctx)                                        # work/bench-A.jsonl，产物在 work/exp/
    here = Path(__file__).resolve().parents[1] / "decide_bench"
    runs = []
    for v in D._vols(ctx):
        runs += ["--run", f"{ctx.book}/{v}={ctx.work / 'exp' / f'bench-{ctx.book}-{v}' / 'A' / v}"]
    cmd = [sys.executable, str(here / "gate_bench.py")] + runs + [
        "--baseline", str(pred), "--out", str(ctx.work / "gate.json"), "--tsv", str(ctx.work / "gate-cells.tsv")]
    D._call(cmd, ctx, "gate.log")
    return ctx.work / "gate.json"


def score(ctx: BenchCtx, pred: Path) -> BenchResult:
    g = json.loads(pred.read_text(encoding="utf-8"))
    tot: dict = {}
    for c in g["per_book"].values():
        for k, v in c.items():
            tot[k] = tot.get(k, 0) + v
    w, r = tot.get("wrong", 0), tot.get("right", 0)
    rate = lambda a, b: round(a / b, 4) if b else None
    m = {"wrong_admit_cells": w, "detect_rate": rate(tot.get("wrong_fail", 0), w), "detect_rate_any": rate(tot.get("wrong_any", 0), w),
         "right_cells": r, "false_alarm_rate": rate(tot.get("right_fail", 0), r), "false_alarm_rate_any": rate(tot.get("right_any", 0), r),
         "pages": tot.get("pages", 0), "pages_fail": tot.get("pages_fail", 0),
         "fail_page_rate": rate(tot.get("pages_fail", 0), tot.get("pages", 0))}
    items = []
    tsv = ctx.work / "gate-cells.tsv"
    if tsv.exists():
        for l in tsv.read_text(encoding="utf-8").splitlines()[1:]:
            k, bk, cls, truth, algo, ch, checks = (l.split("\t") + [""] * 7)[:7]
            fail = any(x.startswith("fail:") for x in checks.split(","))
            items.append({"id": k, "cls": cls, "ok": fail if cls == "wrong" else not fail, "checks": checks})
    return BenchResult("decide-gate", ctx.book, D._vols(ctx), m, "detect_rate", items=items, n=w + r)


register(BenchSpec(
    id="decide-gate", title="decide_gate 检测（放错字检出率、放对误报率）",
    steps=("decide_gate",), owner="CV4", gold={b: "decide-bench/small" for b in D.BOOKS},
    needs=("gold", "config", "code", "raw", "glyph_lib", "models", "corpus"), primary="detect_rate", run=run, score=score,
    cost="heavy", guards=(Guard("false_alarm_rate", "max", 0.005),),
    item_key="id", item_ok="ok", plan=D.plan,
    args={"set": "small｜large（缺省 small）"}))
