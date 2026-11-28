"""decide：第四步定字（CV4 decide-bench，`eval/decide_bench/`）接统一接口（CV0 2026-11-28 样板，CV4 审）。

资源：`dataset`＝测试集仓根（`decide-bench/<集>/` bench.yaml＋items.jsonl，按 `ws` 分书）；`ws`＝已 `guji db pull` 的
工作区（册配置、书仓 `code/`、钉版字形库、模型、语料齐）。冻结快照（产物包）由 decide_bench.run 按 bench.yaml
的 label 取回并核 digest。参数：`--arg set=small|large`、`--arg layer=frozen|dyn`（dyn 待接）。
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register

SETS = ("small", "large")
BOOKS = ("988g3f0wsu", "995ejelvk0", "siku-zongmu", "99k3i35yww")
OK = ("放对", "拦住·首选对")


def _shard(ctx: BenchCtx) -> Path:
    s = ctx.args.get("set", "small")
    if s not in SETS:
        raise ValueError(f"decide 的 set 只有 {SETS}")
    return Path(ctx.res["dataset"]) / "decide-bench" / s


def _book_vols(shard: Path, book: str, vols: list) -> list[str]:
    b = yaml.safe_load((Path(shard) / "bench.yaml").read_text(encoding="utf-8"))
    return [str(x["vol"]) for x in b["books"] if x["ws"] == book and (not vols or str(x["vol"]) in vols)]


def plan(gold: Path, book: str, vols: list) -> dict:
    """册清单（small＋large 都算，manager 按它建钉版字形库）；不用原图，页是 None。"""
    out: dict = {}
    for s in SETS:
        p = Path(gold).parent / s
        if (p / "bench.yaml").exists():
            out.update({v: None for v in _book_vols(p, book, vols)})
    return out


def _vols(ctx: BenchCtx) -> list[str]:
    return _book_vols(_shard(ctx), ctx.book, ctx.vols)


def run(ctx: BenchCtx) -> Path:
    if ctx.args.get("layer", "frozen") != "frozen":
        raise NotImplementedError("decide 的 dyn 层还没接（CV4 P1）")
    vols = _vols(ctx)
    if not vols:
        raise LookupError("no_gold")
    here = Path(__file__).resolve().parents[1] / "decide_bench"
    cmd = [sys.executable, str(here / "run.py"), "--shard", str(_shard(ctx)), "--ws", f"{ctx.book}={ctx.res['ws']}",
           "--work", str(ctx.work), "--name", "bench", "--books", ",".join(vols), "--no-warm-check",
           "--guji", str(Path(sys.executable).with_name("guji"))]
    if ctx.params:
        raise NotImplementedError("decide 的 A/B 用 guji bench ab（P1）；run 只跑现行")
    env = {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "GUJI_LLM_ONLINE")}
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    (ctx.work / "run.log").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"decide-bench 跑失败（日志 {ctx.work}/run.log）：{r.stderr[-500:]}")
    return ctx.work / "bench-A.jsonl"


def score(ctx: BenchCtx, pred: Path) -> BenchResult:
    rows = [json.loads(l) for l in pred.read_text(encoding="utf-8").splitlines() if l.strip()]
    c = collections.Counter(r["outcome"] for r in rows)
    n = len(rows) or 1
    adm = c["放对"] + c["放成异体"] + c["放错字"]
    rv = c["拦住·首选对"] + c["拦住·首选错"]
    m = {"wrong_admit": c["放错字"], "variant_admit": c["放成异体"], "admit_rate": round(adm / n, 4),
         "review_top1_ok": round(c["拦住·首选对"] / rv, 4) if rv else None, "missing": c["缺格"],
         "missing_rate": round(c["缺格"] / n, 4),
         "outcomes": dict(c)}
    items = [{"id": r["id"], "ok": r["outcome"] in OK, "outcome": r["outcome"], "algo": r.get("algo"),
              "truth": r.get("truth"), **({"cmp_skip": True} if r["outcome"] == "缺格" else {})} for r in rows]
    return BenchResult("decide", ctx.book, _vols(ctx), m, "wrong_admit", items=items, n=len(rows))


register(BenchSpec(
    id="decide", title="第四步定字收尾（放错字必须 0、放行率、人审首选对率）",
    steps=("align_ref", "context_decide", "cell_state", "group_decision", "char_decide"), owner="CV4",
    gold={b: "decide-bench/small" for b in BOOKS}, needs=("gold", "config", "code", "raw", "glyph_lib", "models", "corpus"),
    primary="wrong_admit", run=run, score=score, cost="heavy",
    # missing_rate：收尾没跑出来的格（缺原图、上游失败）也是 0 放错字，不拦就成了假通过
    guards=(Guard("wrong_admit", "max", 0), Guard("missing_rate", "max", 0.01), Guard("flip_worse", "max", 0)),
    suites=("decide",),
    item_key="id", item_ok="ok", plan=plan,
    args={"set": "small｜large（缺省 small）", "layer": "frozen｜dyn（缺省 frozen；dyn 待接）"}))
