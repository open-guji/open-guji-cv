"""4b 上下文（文意）三项 bench（CV4，接统一接口，2026-11-28；原在 manager `eval/registry.py`，GM3 移交 CV4）：

- `llm-context`：外部大模型在「现行 gated_ngram 判错」的槽位上救回多少（题集＝缓存快照覆盖的 100 题，evalset 共 150 题）。**缺省只读裁定缓存，不联网**：
  缓存是 dataset `context-correction/llm-cache/<日期>.jsonl`（kind=ctx_ruling，键＝格号＋model＋prompt_ver），
  文件 sha256 写进结果 `env.llm_cache_sha256`，同缓存同题集两次结果逐位相同。题集在本仓 `output/llm_context_evalset/evalset.json`。
  `--arg online=1` 才走旧脚本在线真调用（要 GLM／DASHSCOPE key，结果不可复现，不进护栏）；llm_online_accuracy 作它的 online 子项（待接，见已知缺口）。
- `confusable-lm`：形近对消歧的 n-gram 臂（`scripts/eval_confusable_lm.py`）。语料路径走 `--arg book_corpus=…,general_corpus=…`
  （manager 资源层还不给语料路径）；`mode` 缺省 heldout（诚实口径，book 对本集有泄漏）。
- `context-correction`：冻结候选上「通用 LM＋本书 LM」纠正（`scripts/eval_context_correction.py`），主指标 top1_gain，看有害翻转率。

三项金标都只有殿本 vol01（`context-correction`、`confusable-context` 分片），其他书报 no_gold。基线数：都还没有。
`eval_context_guard`（基线对变体的 A/B 工具，没有金标）不在这里，等 `guji bench ab` 能传变体产物后再接。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register

BOOK = "96mid1ogzk"
REPO = Path(__file__).resolve().parents[3]
EVALSET = REPO / "output" / "llm_context_evalset" / "evalset.json"
DEFAULT_MODEL, DEFAULT_PROMPT = "glm-4-plus", "candidates"


def _need_book(ctx: BenchCtx) -> None:
    if ctx.book != BOOK:
        raise LookupError("no_gold")


def _sha256(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _cache_path(ctx: BenchCtx) -> Path:
    if ctx.args.get("cache"):
        return Path(ctx.args["cache"])
    d = Path(ctx.res["dataset"]) / "context-correction" / "llm-cache"
    fs = sorted(d.glob("*.jsonl"))
    if not fs:
        raise FileNotFoundError(f"{d} 下没有 llm 裁定缓存快照（*.jsonl）；缺它 llm-context 没有可复现的答案")
    return fs[-1]


def load_rulings(path: Path, model: str, prompt_ver: str) -> dict[str, dict]:
    """裁定缓存快照 → {格号: 记录}，只取这个 model＋prompt_ver 的 llm 裁定。"""
    out: dict[str, dict] = {}
    for l in Path(path).read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("kind") == "ctx_ruling" and r.get("source") == "llm" and r.get("model") == model and r.get("prompt_ver") == prompt_ver:
            out[r["cell"]] = r
    return out


def snapshot_cells(path: Path) -> set[str]:
    """快照里出现过的格（任何 model／prompt）＝这份缓存定下的题集。evalset 有 150 题，历史报告只跑过其中 100 题。"""
    out = set()
    for l in Path(path).read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            if r.get("kind") == "ctx_ruling" and r.get("source") == "llm":
                out.add(r["cell"])
    return out


def score_llm_context(items: list[dict], rulings: dict[str, dict], questions: set[str] | None = None) -> tuple[dict, list[dict]]:
    """`questions`：题集（格号）；缺省全部 items。题集内某题没有这个 model＋prompt 的裁定，记 cache_miss。"""
    if questions is not None:
        items = [it for it in items if it["id"] in questions]
    n = len(items)
    rows = []
    for it in items:
        r = rulings.get(it["id"])
        got = r["char"] if r else None
        rows.append({"id": it["id"], "gold": it["gold"], "llm": got, "ok": got == it["gold"], "miss": r is None,
                     "in_candidates": bool(r and r.get("in_candidates"))})
    ok, miss = sum(r["ok"] for r in rows), sum(r["miss"] for r in rows)
    rate = lambda a, b: round(a / b, 4) if b else None
    m = {"llm_accuracy": rate(ok, n), "rescued": ok, "cache_miss": miss, "cache_miss_rate": rate(miss, n),
         "in_candidates_rate": rate(sum(r["in_candidates"] for r in rows), n), "n": n,
         "current_strategy_accuracy": 0.0}              # 题集按构造＝现行策略全错
    return m, rows


# ---------------------------------------------------------------- llm-context
def _run_llm(ctx: BenchCtx) -> Path:
    _need_book(ctx)
    out = ctx.work / "llm-context.json"
    if ctx.args.get("online") == "1":                    # 在线真调用：旧脚本，不可复现
        prov = ctx.args.get("provider", "glm")
        cmd = [sys.executable, str(REPO / "scripts" / "eval_llm_context.py"), str(EVALSET), "--provider", prov,
               "--prompt-version", ctx.args.get("prompt", DEFAULT_PROMPT), "--out", str(out)]
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env={**__import__("os").environ, "PYTHONPATH": str(REPO)})
        if r.returncode:
            raise RuntimeError(f"在线评测失败：{(r.stdout + r.stderr)[-400:]}")
        return out
    cache = _cache_path(ctx)
    items = json.loads(EVALSET.read_text(encoding="utf-8"))["items"]
    model, pv = ctx.args.get("model", DEFAULT_MODEL), ctx.args.get("prompt", DEFAULT_PROMPT)
    m, rows = score_llm_context(items, load_rulings(cache, model, pv), snapshot_cells(cache))
    out.write_text(json.dumps({"mode": "cache", "model": model, "prompt_ver": pv, "cache": str(cache), "cache_sha256": _sha256(cache),
                               "evalset_sha256": _sha256(EVALSET), "metrics": m, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _score_llm(ctx: BenchCtx, pred: Path) -> BenchResult:
    d = json.loads(pred.read_text(encoding="utf-8"))
    if d.get("mode") == "cache":
        r = BenchResult("llm-context", ctx.book, ctx.vols, d["metrics"], "llm_accuracy", n=d["metrics"]["n"],
                        items=[{"id": x["id"], "ok": x["ok"], "llm": x["llm"], "gold": x["gold"]} for x in d["rows"]],
                        env={"llm_cache_sha256": d["cache_sha256"], "llm_cache": Path(d["cache"]).name, "model": d["model"],
                             "prompt_ver": d["prompt_ver"], "evalset_sha256": d["evalset_sha256"]})
        return r
    m = {"llm_accuracy": d.get("llm_accuracy"), "parse_fail_rate": d.get("llm_parse_fail_rate"), "n": d.get("n"),
         "cache_miss_rate": 0.0}                       # 在线口径无缓存缺失
    return BenchResult("llm-context", ctx.book, ctx.vols, m, "llm_accuracy", n=d.get("n") or 0,
                       items=[{"id": x["id"], "ok": x["llm_correct"]} for x in d.get("rows", [])],
                       env={"online": True, "provider": d.get("provider"), "model": d.get("model")},
                       reason="在线口径，不可复现，不进护栏")


# ---------------------------------------------------------------- 调脚本的两项
def _script(ctx: BenchCtx, cmd: list, log: str) -> None:
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                       env={**__import__("os").environ, "PYTHONPATH": str(REPO), "PYTHONIOENCODING": "utf-8"})
    (ctx.work / log).write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"{cmd[1]} 失败（日志 {ctx.work}/{log}）：{(r.stdout + r.stderr)[-400:]}")


def _corpus_args(ctx: BenchCtx) -> list[str]:
    out: list[str] = []
    for key, flag in (("book_corpus", "--book-corpus"), ("general_corpus", "--general-corpus")):
        for p in [x for x in ctx.args.get(key, "").split(",") if x]:
            out += [flag, p]
    return out


def _run_confusable(ctx: BenchCtx) -> Path:
    _need_book(ctx)
    cargs = _corpus_args(ctx)
    if not cargs:
        raise RuntimeError("confusable-lm 要语料：--arg book_corpus=<路径,…> general_corpus=<路径,…>（manager 资源层暂不提供语料路径）")
    out = ctx.work / "confusable.json"
    cases = Path(ctx.res["dataset"]) / "confusable-context" / "cases.json"
    _script(ctx, [sys.executable, str(REPO / "scripts" / "eval_confusable_lm.py"), str(cases), "--mode", ctx.args.get("mode", "heldout"),
                  "--out", str(out)] + cargs, "confusable.log")
    return out


def score_confusable(results: list[dict]) -> tuple[dict, list[dict]]:
    rate = lambda a, b: round(a / b, 4) if b else None
    hard = [r for r in results if r["tier"] == "hard_ref_silent"]
    easy = [r for r in results if r["tier"] == "easy_ref_gives_answer"]
    m = {"accuracy": rate(sum(r["correct"] for r in results), len(results)), "acc_hard": rate(sum(r["correct"] for r in hard), len(hard)),
         "acc_easy": rate(sum(r["correct"] for r in easy), len(easy)), "n": len(results), "n_hard": len(hard)}
    return m, [{"id": r["id"], "ok": r["correct"], "pair": r["pair"], "pick": r["pick"], "gold": r["gold"], "tier": r["tier"]} for r in results]


def _score_confusable(ctx: BenchCtx, pred: Path) -> BenchResult:
    d = json.loads(pred.read_text(encoding="utf-8"))
    m, items = score_confusable(d["results"])
    return BenchResult("confusable-lm", ctx.book, ctx.vols, m, "acc_hard", items=items, n=len(items), env={"arm": d.get("arm")})


def _run_cc(ctx: BenchCtx) -> Path:
    _need_book(ctx)
    cargs = _corpus_args(ctx)
    if not cargs:
        raise RuntimeError("context-correction 要语料：--arg book_corpus=<路径> general_corpus=<路径>（manager 资源层暂不提供语料路径）")
    out = ctx.work / "cc.json"
    w = ctx.args.get("weight", "0.9")
    _script(ctx, [sys.executable, str(REPO / "scripts" / "eval_context_correction.py"), str(Path(ctx.res["dataset"]) / "context-correction"),
                  "--sweep", w, "--gate", ctx.args.get("gate", "0.70"), "--out", str(out)] + cargs, "cc.log")
    return out


def score_cc(report: dict, weight: float = 0.9) -> dict:
    rows = [r for r in report["rows"] if r.get("book_weight") == weight]
    if not rows:
        raise RuntimeError(f"报告里没有 book_weight={weight} 的行")
    r = rows[0]
    return {"top1_gain": r["top1_gain"], "top1": r["top1"], "baseline_top1": r["baseline_top1"], "rescued": r["rescued"], "harmed": r["harmed"],
            "harmful_flip_rate": r["harmful_flip_rate"], "glyph_layer_immutable": int(bool(r["glyph_layer_immutability"])), "n": r["n"]}


def _score_cc(ctx: BenchCtx, pred: Path) -> BenchResult:
    d = json.loads(pred.read_text(encoding="utf-8"))
    m = score_cc(d, float(ctx.args.get("weight", "0.9")))
    return BenchResult("context-correction", ctx.book, ctx.vols, m, "top1_gain", n=m["n"], items=[],
                       env={"provenance": d.get("provenance")})


_GOLD = lambda shard: {BOOK: shard}                                    # noqa: E731 —— 三项都只有殿本 vol01
register(BenchSpec(
    id="llm-context", title="外部大模型在 ngram 判错槽位上的救回率（缺省只读裁定缓存，不联网）", steps=("context_decide",), owner="CV4",
    gold=_GOLD("context-correction"), needs=("gold",), primary="llm_accuracy", run=_run_llm, score=_score_llm, cost="light",
    guards=(Guard("cache_miss_rate", "max", 0.0),), item_key="id", item_ok="ok",
    args={"online": "1＝在线真调用（要 key，不可复现）", "model": f"缓存里的 model（缺省 {DEFAULT_MODEL}）", "prompt": f"prompt_ver（缺省 {DEFAULT_PROMPT}）",
          "cache": "裁定缓存路径（缺省取 dataset context-correction/llm-cache 最新一份）"}))
register(BenchSpec(
    id="confusable-lm", title="形近对消歧 n-gram 臂（真难档准确率）", steps=("context_decide",), owner="CV4",
    gold=_GOLD("confusable-context"), needs=("gold", "corpus"), primary="acc_hard", run=_run_confusable, score=_score_confusable, cost="heavy",
    item_key="id", item_ok="ok",
    args={"book_corpus": "本书语料路径，逗号分隔", "general_corpus": "通用语料路径，逗号分隔", "mode": "book｜heldout｜general（缺省 heldout）"}))
register(BenchSpec(
    id="context-correction", title="冻结候选上的 LM 上下文纠正（top1 增益、有害翻转率）", steps=("context_decide",), owner="CV4",
    gold=_GOLD("context-correction"), needs=("gold", "corpus"), primary="top1_gain", run=_run_cc, score=_score_cc, cost="heavy",
    guards=(Guard("glyph_layer_immutable", "min", 1),), item_key="id", item_ok="ok",
    args={"book_corpus": "本书语料路径", "general_corpus": "通用语料路径", "weight": "本书 LM 权重（缺省 0.9）", "gate": "门槛（缺省 0.70，生产口径）"}))
