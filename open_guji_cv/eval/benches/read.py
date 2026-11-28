"""第三步识字的 bench（CV3，2026-11-28）接统一接口：包现成的 `scripts/eval_*.py`，按书取分片、出逐样本清单。

| bench id | 量什么 | 老评测器（`guji eval run`） |
|---|---|---|
| `read-3a-advset` | 3a 库外拒识：库里没有的字被生产判官判 same（形近层题数） | advset、advset_shiji、advset_qtw |
| `read-3a-damaged` | 3a 真实残损格：首位、放行、误放 | match_pool、match_pool_shiji |
| `read-3b-near` | 3b 形近字组整体：触发、覆盖、组内判对／误判、弃权、ECE、耗时 | near |

护栏阈值在 dataset `guards/read.yaml`（按书按集；本模块按 `bench:`＋`ws:` 两个键取，见 `dataset_guards`），
不写在登记项里；登记项只带 `flip_worse ≤ 0`（带 `--against` 时才有值）。
指标名与老框架（manager `eval/extract.py`）一字不差，护栏表两边通用。

脚本在 cv 仓的 `scripts/` 下：只支持检出安装（`pip install -e`），找不到脚本报 skipped。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register, skipped

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "scripts"
#: 殿本用书 id 96mid1ogzk（同 cut-2d、decide；dataset 里有的地方记旧工作区名 siku-zongmu）
SIKU, SHIJI, QTW = "96mid1ogzk", "988g3f0wsu", "995ejelvk0"
#: 跳过记号：run 返回它，score 照它出 skipped（run 里缺件不算跑崩）
_SKIP = "SKIP.txt"


# ------------------------------------------------------------------ 共用
def _skip(ctx: BenchCtx, why: str) -> Path:
    p = Path(ctx.work) / _SKIP
    p.write_text(why, encoding="utf-8")
    return p


def _skipped(spec_id: str, ctx: BenchCtx, pred: Path) -> BenchResult | None:
    if Path(pred).name != _SKIP:
        return None
    from ..bench import get
    return skipped(get(spec_id), ctx, Path(pred).read_text(encoding="utf-8"))


def _script(ctx: BenchCtx, name: str, argv: list[str], log: str) -> None:
    """跑 `scripts/<name>`（cwd＝cv 仓根，`PYTHONPATH=.`）；不在线问大模型。非零退出抛错（记 failed）。"""
    env = {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "GUJI_LLM_ONLINE")}
    env["PYTHONPATH"] = str(REPO) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / name), *argv], cwd=str(REPO), env=env,
                       capture_output=True, text=True, check=False)
    (Path(ctx.work) / log).write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"{name} 失败（日志 {ctx.work}/{log}）：{r.stderr[-500:]}")


def _need_script(ctx: BenchCtx, name: str) -> Path | None:
    if (SCRIPTS / name).is_file():
        return None
    return _skip(ctx, f"cv 仓里没有 scripts/{name}（第三步 bench 只支持检出安装：pip install -e open-guji-cv）")


def _need_models(ctx: BenchCtx, rel: str) -> Path | None:
    """cv 仓 `models/` 下的文件；缺了按 `config/model-registry.json` 从 R2 取回，取不到报 skipped。"""
    if (REPO / rel).is_file():
        return None
    try:
        from ...ops.model_blobs import ensure_repo_models
        ensure_repo_models()
    except Exception:                                      # noqa: BLE001
        pass
    if (REPO / rel).is_file():
        return None
    return _skip(ctx, f"缺模型 {rel}：设好 R2 读令牌后 `guji model fetch`（或跑一次 guji pipeline 自动取回）")


def dataset_guards(bench_id: str, book: str, dataset: str | Path | None) -> list[dict]:
    """dataset `guards/*.yaml` 里 `bench: <id>` 且 `ws: <书id>` 的护栏（`metric`、`dir`、`limit`、`baseline`…）。"""
    if not dataset:
        return []
    d = Path(dataset) / "guards"
    if not d.is_dir():
        return []
    import yaml
    out = []
    for f in sorted(d.glob("*.yaml")):
        for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("guards") or []:
            if g.get("bench") == bench_id and str(g.get("ws")) == book:
                out.append(g)
    return out


def apply_dataset_guards(r: BenchResult, ctx: BenchCtx) -> BenchResult:
    """按护栏表逐条判（同 `bench.apply_guards` 的口径）；越线 → regressed，指标缺了记 unverified（不算过）。"""
    for g in dataset_guards(r.bench, ctx.book, ctx.res.get("dataset")):
        gd = Guard(str(g["metric"]), g["dir"], float(g["limit"]))
        v = r.metrics.get(gd.metric)
        st = gd.check(v)
        r.guards.append({"metric": gd.metric, "dir": gd.dir, "limit": gd.limit, "value": v, "status": st,
                         "baseline": g.get("baseline"), "src": "dataset guards"})
        if st in ("regressed", "unverified") and r.status == "ok":
            r.status = "regressed"
            r.reason = r.reason or f"护栏 {gd.metric}：{v}（{'≤' if gd.dir == 'max' else '≥'} {gd.limit}）"
    return r


def _pct(x):
    return None if x is None else round(100.0 * x, 2)


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


# ------------------------------------------------------------------ 3a 库外拒识（advset）
ADVSET = {SIKU: "glyph-match/advset-siku-v2", SHIJI: "glyph-match/advset-shiji", QTW: "glyph-match/advset-qtw"}
#: 各书生产判官：全唐文 CNN＋fuse（glyph_sim_qtw），殿本、史記覆盖分（同老评测器；`--arg sim_model=` 换）
ADVSET_SIM = {QTW: "models/glyph_sim_qtw/model.pt"}


def _sim_model(ctx: BenchCtx) -> str:
    m = ctx.args.get("sim_model", ADVSET_SIM.get(ctx.book, ""))
    return "" if m in ("", "none", "cov") else m


def advset_run(ctx: BenchCtx) -> Path:
    if (s := _need_script(ctx, "eval_advset.py")):
        return s
    sim = _sim_model(ctx)
    if sim and (s := _need_models(ctx, sim)):
        return s
    out = Path(ctx.work) / "advset.json"
    argv = [ctx.res["gold"], "--out", str(out), "--workers", ctx.args.get("workers", "4")]
    if sim:
        argv += ["--sim-model", sim]
    _script(ctx, "eval_advset.py", argv, "advset.log")
    return out


def advset_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    if (r := _skipped("read-3a-advset", ctx, pred)):
        return r
    d = json.loads(Path(pred).read_text(encoding="utf-8"))
    h = d["headline"]
    way = h["way"]
    res = d["result"][way]
    near, var = res["形近"], res["异体"]
    m = {"形近误认": h["near_false_same"], "形近误认率": _pct(h["near_false_same_rate"]),
         "其中对家": near["partner_false_same"], "异体下 same": h["variant_false_same"],
         "n_query": near["n_query"], "test 形近误认": near["by_split"]["test"], "判官": way,
         "sim_model": d.get("sim_model")}
    bad_near = {x.split("|", 1)[0] for x in d["flips"].get(f"{way}|形近", [])}
    bad_var = {x.split("|", 1)[0] for x in d["flips"].get(f"{way}|异体", [])}
    qids = sorted({it["query_id"] for it in _read_jsonl(Path(ctx.res["gold"]) / "items.jsonl")})
    items = [{"id": q, "ok": q not in bad_near, "variant_same": q in bad_var} for q in qids]
    r = BenchResult("read-3a-advset", ctx.book, ctx.vols, m, "形近误认", items=items, n=len(qids),
                    env={"sim_model": d.get("sim_model")})
    return apply_dataset_guards(r, ctx)


register(BenchSpec(
    id="read-3a-advset", title="3a 库外拒识（库里没有的字被判 same，形近层题数）", steps=("glyph_match",), owner="CV3",
    gold=ADVSET, needs=("gold",), primary="形近误认", run=advset_run, score=advset_score, mode="run", cost="heavy",
    guards=(Guard("flip_worse", "max", 0),), suites=("read", "read-3a"), item_key="id", item_ok="ok",
    args={"sim_model": "相似度模型（缺省按书：全唐文 models/glyph_sim_qtw/model.pt，殿本、史記覆盖分；cov＝只覆盖分）",
          "workers": "进程数（缺省 4）"}))


# ------------------------------------------------------------------ 3a 真实残损（match_pool）
DAMAGED = {SIKU: "glyph-match/damaged-siku-v2", SHIJI: "glyph-match/damaged-shiji"}


def damaged_run(ctx: BenchCtx) -> Path:
    if (s := _need_script(ctx, "eval_match_pool.py")):
        return s
    sim = _sim_model(ctx)
    if sim and (s := _need_models(ctx, sim)):
        return s
    out = Path(ctx.work) / "match_pool.json"
    argv = [ctx.res["gold"], "--out", str(out), "--workers", ctx.args.get("workers", "4")]
    if sim:
        argv += ["--sim-model", sim]
    _script(ctx, "eval_match_pool.py", argv, "match_pool.log")
    return out


def damaged_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    if (r := _skipped("read-3a-damaged", ctx, pred)):
        return r
    d = json.loads(Path(pred).read_text(encoding="utf-8"))
    h = d["headline"]
    res = d["result"][h["way"]]
    m = {"误放": h["false_same"], "判官": h["way"]}
    for k in ["全部"] + sorted(x for x in res if x != "全部"):
        v = res[k]
        m[f"{k} 首位"] = _pct(v["rank1_rate"])
        m[f"{k} 放行"] = _pct(v["accept_rate"])
    bad = {}
    for x in d["flips"].get(h["way"], []):
        bad[x.split("|", 1)[0]] = "（误放）" in x
    its = _read_jsonl(Path(ctx.res["gold"]) / "items.jsonl")
    items = [{"id": it["query_id"], "ok": it["query_id"] not in bad, "kind": it.get("kind"),
              "false_same": bad.get(it["query_id"], False)} for it in its]
    r = BenchResult("read-3a-damaged", ctx.book, ctx.vols, m, "误放", items=items, n=len(items),
                    env={"sim_model": d.get("sim_model")})
    return apply_dataset_guards(r, ctx)


register(BenchSpec(
    id="read-3a-damaged", title="3a 真实残损格（误放、首位、放行，分残笔／细笔／对照）", steps=("glyph_match",),
    owner="CV3", gold=DAMAGED, needs=("gold",), primary="误放", run=damaged_run, score=damaged_score, mode="run",
    guards=(Guard("flip_worse", "max", 0),), suites=("read", "read-3a"), item_key="id", item_ok="ok",
    args={"sim_model": "同 read-3a-advset", "workers": "进程数（缺省 4）"}))


# ------------------------------------------------------------------ 3b 形近字组整体（near）
NEAR_SHARD = "glyph-near/bench3b"


def _near_key(gold: Path, book: str) -> str | None:
    """bench.json 的书键（殿本键是书 id 96mid1ogzk、工作区 siku-zongmu），按键或 `ws` 对。"""
    b = json.loads((Path(gold) / "bench.json").read_text(encoding="utf-8"))["books"]
    return next((k for k, v in b.items() if k == book or v.get("ws") == book), None)


def near_plan(gold: Path, book: str, vols: list) -> dict:
    b = json.loads((Path(gold) / "bench.json").read_text(encoding="utf-8"))["books"]
    k = _near_key(gold, book)
    if k is None:
        return {}
    return {v: None for v, x in b[k]["vols"].items() if x["role"] == "test" and (not vols or v in vols)}


def near_run(ctx: BenchCtx) -> Path:
    if (s := _need_script(ctx, "eval_near.py")):
        return s
    key = _near_key(Path(ctx.res["gold"]), ctx.book)
    if key is None:
        raise LookupError("no_gold")
    out, rows = Path(ctx.work) / "near.json", Path(ctx.work) / "near-rows.jsonl"
    data = Path(ctx.res["data"]).parent                    # 分支层（含 <工作区 id>/）
    argv = [ctx.res["gold"], "--out", str(out), "--rows", str(rows), "--data", str(data), "--books", key,
            "--repeat", ctx.args.get("repeat", "50")]
    if ctx.args.get("calib_dir"):
        argv += ["--calib-dir", ctx.args["calib_dir"]]
    _script(ctx, "eval_near.py", argv, "near.log")
    return out


def near_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    if (r := _skipped("read-3b-near", ctx, pred)):
        return r
    d = json.loads(Path(pred).read_text(encoding="utf-8"))
    bk = next(iter(d["books"]))
    if "error" in d["books"][bk]:
        raise RuntimeError(d["books"][bk]["error"])
    hl = d.get("headline") or []
    wrong, right, decided = (sum(h.get(k) or 0 for h in hl) for k in ("wrong", "right", "decided"))
    per = {f"{h['method']}:{h['group']}": {k: h.get(k) for k in ("triggered", "scored", "decided", "right", "wrong",
                                                                    "acc", "abstain_rate", "ms_per_cell", "ece")}
           | {"coverage": (h.get("coverage") or {}).get("rate")} for h in hl}
    rep = d["books"][bk]
    missing = sorted(k for k, v in (rep.get("models") or {}).items() if "error" in v)
    m = {"组内误判": wrong, "判对": right, "判出": decided, "准确率": _pct(right / decided) if decided else None,
         "方法数": len(hl), "缺模型": len(missing), "跳过方法": len(rep.get("skipped_methods") or []),
         "by_method": per}
    if missing:
        m["missing_models"] = missing
    items = _read_jsonl(Path(ctx.work) / "near-rows.jsonl")
    r = BenchResult("read-3b-near", ctx.book, ctx.vols, m, "组内误判", items=items, n=len(items),
                    env={"methods_sha": d.get("methods_sha", {}).get(bk)})
    return apply_dataset_guards(r, ctx)


register(BenchSpec(
    id="read-3b-near", title="3b 形近字组整体（组内误判、判对、弃权、覆盖、ECE、耗时）", steps=("glyph_near",),
    owner="CV3", gold={SIKU: NEAR_SHARD, SHIJI: NEAR_SHARD, QTW: NEAR_SHARD}, needs=("gold", "config"),
    primary="组内误判", run=near_run, score=near_score, mode="run", plan=near_plan,
    guards=(Guard("flip_worse", "max", 0), Guard("缺模型", "max", 0)), suites=("read", "near"),
    item_key="id", item_ok="ok",
    args={"repeat": "每个方法重打一遍比逐位相同的格数（缺省 50，0 不比）",
          "calib_dir": "临时校准表根（叠在模型上算 ECE）"}))


# ------------------------------------------------------------------ （旧）生僻字候选（rare_candidates，退役中）
RARE = {SIKU: "char-clustering/samples/004-siku-v2-human", SHIJI: "char-clustering/samples/005-shiji-human",
        QTW: "char-clustering/samples/006-qtw-human"}
RARE_FIRSTSEEN = {QTW: "char-clustering/samples/007-qtw-firstseen"}
RARE_CHARSET = "unicode-cjk-ab"


def _rare_index_missing() -> str | None:
    """emb 检索要的全字表模板索引（`models/<ckpt>/emb_*.npz`）；不在就不跑（现建要几十分钟，且缺了会静默出 0%）。"""
    from ...clustering.charset_spec import base_charset
    from ...clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates
    inst = CnnCandidates(str(DEFAULT_CKPT))
    if not inst.available:
        return f"缺 CNN 权重 {DEFAULT_CKPT}（guji model fetch）"
    _k, f, _x = inst.emb_index_key(base_charset(RARE_CHARSET))
    if not f.exists():
        return f"缺向量模板索引 {f.name}：先 `guji cache pull-rare-index --charset {RARE_CHARSET}`"
    return None


def rare_run(ctx: BenchCtx) -> Path:
    if (s := _need_script(ctx, "eval_oov.py")):
        return s
    if (why := _rare_index_missing()):
        return _skip(ctx, why)
    out, rows = Path(ctx.work) / "oov.json", Path(ctx.work) / "oov-rows.jsonl"
    _script(ctx, "eval_oov.py", ["--bench", ctx.res["gold"], "--items", "rare.jsonl", "--charset", RARE_CHARSET,
                                 "--json", str(out), "--rows", str(rows)], "oov.log")
    return out


def _rare_score(bench_id: str, primary: str, ctx: BenchCtx, pred: Path) -> BenchResult:
    if (r := _skipped(bench_id, ctx, pred)):
        return r
    d = json.loads(Path(pred).read_text(encoding="utf-8"))
    res = d["result"]
    emb = res.get("emb") or {}
    m = {"emb top1": emb.get("top1"), "emb top10": emb.get("top10")}
    for k, v in sorted(res.items()):
        if k.startswith("emb_") and isinstance(v, dict):
            m[f"{k[4:]} top1"], m[f"{k[4:]} top10"] = v.get("top1"), v.get("top10")
    m = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()}
    if d.get("n") and not emb.get("top10"):
        raise RuntimeError("emb top10 为 0：多半向量包坏了（静默假数，判失败）")
    items = _read_jsonl(Path(ctx.work) / "oov-rows.jsonl")
    r = BenchResult(bench_id, ctx.book, ctx.vols, m, primary, items=items, n=len(items),
                    env={"ckpt": d.get("ckpt"), "charset": d.get("charset")})
    return apply_dataset_guards(r, ctx)


def rare_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    return _rare_score("read-rare", "unseen top10", ctx, pred)


def rare_firstseen_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    return _rare_score("read-rare-firstseen", "emb top10", ctx, pred)


_RARE_ARGS = {}
register(BenchSpec(
    id="read-rare", title="（旧）生僻字候选：本书人裁少见字，emb 检索 unicode-cjk-ab 全表前 10 命中（分 unseen／oov）",
    steps=("rare_candidates",), owner="CV3", gold=RARE, needs=("gold", "torch"), primary="unseen top10",
    run=rare_run, score=rare_score, mode="run", cost="heavy", guards=(Guard("flip_worse", "max", 0),),
    suites=("read", "read-rare"), item_key="id", item_ok="ok", args=_RARE_ARGS))
register(BenchSpec(
    id="read-rare-firstseen", title="（旧）生僻字候选：全唐文首次字头格（库例 0–2，Sheldon 逐格选字）emb 前 10",
    steps=("rare_candidates",), owner="CV3", gold=RARE_FIRSTSEEN, needs=("gold", "torch"), primary="emb top10",
    run=rare_run, score=rare_firstseen_score, mode="run", cost="heavy", guards=(Guard("flip_worse", "max", 0),),
    suites=("read", "read-rare"), item_key="id", item_ok="ok", args=_RARE_ARGS))
