"""decide：第四步定字（CV4 decide-bench，`eval/decide_bench/`）接统一接口（CV0 2026-11-28 样板，CV4 审）。

资源：`dataset`＝测试集仓根（`decide-bench/<集>/` bench.yaml＋items.jsonl，按 `ws` 分书）；`ws`＝已 `guji db pull` 的
工作区（册配置、书仓 `code/`、钉版字形库、模型、语料齐）。冻结快照（产物包）由 decide_bench.run 按 bench.yaml
的 label 取回并核 digest。参数：`--arg set=small|large`、`--arg layer=frozen|dyn`（dyn：取各册现行 main 包、按原图框重绑，
金标取 small＋large 两个集，`set` 不起作用）。

结果里除收尾口径外按子步分节：a4（对位）、b4（上下文）、c4（格况）、d4（字组），键前缀即节名；错因位置计数在 `errloc`。
同模块还登记 `decide-gate`（decide_gate 的检出率与误报率）。
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
BOOKS = ("988g3f0wsu", "995ejelvk0", "96mid1ogzk", "99k3i35yww")
#: 书 id → dataset 分片里 anchor／bench.yaml 用的 ws 写法（殿本在 dataset 里是旧名 siku-zongmu，真 id 是 96mid1ogzk，11-28 CV2 指出）。
#: 分片的 ws 字段不改（历史金标、翻转清单、报告都按它），只在这里认。
DATASET_WS = {"96mid1ogzk": "siku-zongmu"}


def dws(book: str) -> str:
    return DATASET_WS.get(book, book)
OK = ("放对", "拦住·首选对")
_FOLD = [set("己已巳"), set("日曰")]          # 同 score.py：组内任一字算对


def _same(x, y) -> bool:
    return x == y or any(x in g and y in g for g in _FOLD)


def _shard(ctx: BenchCtx) -> Path:
    s = ctx.args.get("set", "small")
    if s not in SETS:
        raise ValueError(f"decide 的 set 只有 {SETS}")
    return Path(ctx.res["dataset"]) / "decide-bench" / s


def _book_vols(shard: Path, book: str, vols: list) -> list[str]:
    b = yaml.safe_load((Path(shard) / "bench.yaml").read_text(encoding="utf-8"))
    return [str(x["vol"]) for x in b["books"] if x["ws"] == dws(book) and (not vols or str(x["vol"]) in vols)]


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


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "GUJI_LLM_ONLINE")}


def _guji() -> str:
    return str(Path(sys.executable).with_name("guji"))


def _call(cmd: list, ctx: BenchCtx, log: str) -> None:
    r = subprocess.run(cmd, env=_env(), capture_output=True, text=True, check=False)
    (ctx.work / log).write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    if r.returncode:
        tail = (r.stdout[-300:] + r.stderr[-300:]).strip()
        raise RuntimeError(f"decide-bench 跑失败（日志 {ctx.work}/{log}，退出码 {r.returncode}）：{tail}")


def run(ctx: BenchCtx) -> Path:
    here = Path(__file__).resolve().parents[1] / "decide_bench"
    if ctx.params:
        raise NotImplementedError("decide 的 A/B 用 guji bench ab（P1）；run 只跑现行")
    layer = ctx.args.get("layer", "frozen")
    if layer == "dyn":
        ds = Path(ctx.res["dataset"]) / "decide-bench"
        shards = [ds / s for s in SETS if (ds / s / "bench.yaml").exists()]
        vols = sorted({v for s in shards for v in _book_vols(s, ctx.book, ctx.vols)})
        if not vols:
            raise LookupError("no_gold")
        cmd = [sys.executable, str(here / "dyn.py")] + sum([["--shard", str(s)] for s in shards], []) + [
            "--ws", f"{dws(ctx.book)}={ctx.res['ws']}", "--work", str(ctx.work), "--name", "dyn", "--books", ",".join(vols),
            "--guji", _guji()]
        _call(cmd, ctx, "dyn.log")
        return ctx.work / "dyn.jsonl"
    if layer != "frozen":
        raise ValueError("decide 的 layer 只有 frozen｜dyn")
    vols = _vols(ctx)
    if not vols:
        raise LookupError("no_gold")
    cmd = [sys.executable, str(here / "run.py"), "--shard", str(_shard(ctx)), "--ws", f"{dws(ctx.book)}={ctx.res['ws']}",
           "--work", str(ctx.work), "--name", "bench", "--books", ",".join(vols), "--no-warm-check", "--guji", _guji()]
    _call(cmd, ctx, "run.log")
    return ctx.work / "bench-A.jsonl"


def _sections(rows: list[dict]) -> dict:
    """子步分节指标（读 score.py 写进每格的子步属性；没有子步属性的旧结果这些键为 None）。"""
    if not rows or "a4" not in rows[0]:
        return {}
    n = len(rows)
    rate = lambda a, b: round(a / b, 4) if b else None
    cx = [r for r in rows if r.get("ctx_char") and r.get("ctx_src") == "context"]
    cx_ok = sum(1 for r in cx if _same(r["ctx_char"], r["truth"]))
    grp = [r for r in rows if r.get("group_mode")]
    return {
        "a4_misaligned": sum(1 for r in rows if r["a4"] == "错位"), "a4_misaligned_rate": rate(sum(1 for r in rows if r["a4"] == "错位"), n),
        "b4_context_n": len(cx), "b4_context_precision": rate(cx_ok, len(cx)),
        "c4_missed_char": sum(1 for r in rows if r.get("c4_flag")),
        "c4_marked_admitted": sum(1 for r in rows if r.get("c4_mark") and not r.get("c4_flag")),
        "c4_excluded_in": sum(1 for r in rows if r.get("c4_excl")),
        "d4_group_n": len(grp), "d4_group_wrong_admit": sum(1 for r in grp if r["outcome"] == "放错字"),
        "d4_group_wrong": sum(1 for r in grp if r["outcome"] in ("放错字", "拦住·首选错")),
        "final_top1_ok": rate(sum(1 for r in rows if r["outcome"] in ("放对", "放成异体", "拦住·首选对")), n),
        "errloc": dict(collections.Counter(r["errloc"] for r in rows if r.get("errloc") not in (None, "—"))),
    }


def score(ctx: BenchCtx, pred: Path) -> BenchResult:
    rows = [json.loads(l) for l in pred.read_text(encoding="utf-8").splitlines() if l.strip()]
    c = collections.Counter(r["outcome"] for r in rows)
    n = len(rows) or 1
    adm = c["放对"] + c["放成异体"] + c["放错字"]
    rv = c["拦住·首选对"] + c["拦住·首选错"]
    m = {"wrong_admit": c["放错字"], "variant_admit": c["放成异体"], "admit_rate": round(adm / n, 4),
         "review_top1_ok": round(c["拦住·首选对"] / rv, 4) if rv else None, "missing": c["缺格"],
         "missing_rate": round(c["缺格"] / n, 4),
         "outcomes": dict(c), **_sections(rows)}
    items = [{"id": r["id"], "ok": r["outcome"] in OK, "outcome": r["outcome"], "algo": r.get("algo"),
              "truth": r.get("truth"), "rule": r.get("rule"), "errloc": r.get("errloc"),
              **({"cmp_skip": True} if r["outcome"] == "缺格" else {})} for r in rows]
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
    args={"set": "small｜large（缺省 small）", "layer": "frozen｜dyn（缺省 frozen；dyn 取现行 main 包，金标 small＋large）"}))
