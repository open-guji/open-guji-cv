"""候选字线两个 bench：`read-3c-cands`（3c 按图给候选）与 `decide-4b-ctx`（4b 按上下文重排、补字）（CV3 2026-11-28）。

共用 dataset `char-candidates/`（一份分片，三书的格混在 items.jsonl 里，按 `book` 字段分书）；算法在
`eval/cands_bench.py`（`scripts/eval_cands.py` 是它的命令行壳，旧 `guji eval run @cands` 仍可用）。

- 金标只收人裁；甲层 A＝三书人裁难格，乙层 B＝发过并有人裁的待审卡（史記只有 81 张）。主指标按甲层，乙层带 `b_` 前缀另报。
- 乙层 3a 用发卡时冻结的 `lib_top`，甲层不用 3a（产物包里的 3a 是人裁入库后现跑的，金标已在库，泄漏）。
- 不需要原图、产物、字形库：每格自带冻结的字块图、前后文、冻结池。r5 权重、全字表向量包、SikuRoBERTa 由 cv 现取，
  所以 `needs` 只列 gold、torch（列 models 会让框架去克隆书仓、拉中心库，用不着）。
- 书 id：框架用工作区 id，殿本是 `siku-zongmu`，测试集里记的是书 id `96mid1ogzk`，下面 `ITEM_BOOK` 对上。
- 参数（`--arg k=v`）：`w` 融合权重（缺省 0.005＝产线）、`ctx_noise` 邻字加噪概率、`limit` 只跑前 N 格（冒烟用）。
  不吃 `--params`（运行覆盖）：这两个 bench 量的是现行代码，A/B 比的是改代码前后的两次结果（`--against`）。
"""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register

#: 框架书 id（工作区 id）→ 测试集 items 里的 `book` 字段
ITEM_BOOK = {"988g3f0wsu": "988g3f0wsu", "995ejelvk0": "995ejelvk0", "siku-zongmu": "96mid1ogzk"}
GOLD = {b: "char-candidates" for b in ITEM_BOOK}
KS3C = (1, 10, 30, 50)


def _ns(ctx: BenchCtx, parts: str, no_mlm: bool) -> Namespace:
    a = ctx.args
    return Namespace(shard=Path(ctx.res["gold"]), part=parts, no_mlm=no_mlm, limit=int(a.get("limit", 0)),
                     w=float(a.get("w", 0.005)), sim_mode="max", ctx_noise=float(a.get("ctx_noise", 0.0)),
                     extra_min_sim=0.70, book=ITEM_BOOK[ctx.book])


def _run(ctx: BenchCtx, parts: str, no_mlm: bool) -> Path:
    from .. import cands_bench as CB
    if ctx.params:
        raise NotImplementedError("候选字 bench 不吃 --params；比改代码前后用 --against")
    st = CB.compute(_ns(ctx, parts, no_mlm), log=lambda m: print(m, flush=True))
    if not st["per"]:
        raise LookupError("no_gold")
    out = ctx.work / "pred"
    out.mkdir(parents=True, exist_ok=True)
    (out / "per.json").write_text(json.dumps(st["per"], ensure_ascii=False), encoding="utf-8")
    emb = getattr(st["img"].pack, "version", None) or str(getattr(st["img"].pack, "spec", ""))
    (out / "meta.json").write_text(json.dumps({
        "n_rows": len(st["rows"]), "nonchar": {f"{k[0]}:{k[1]}": v for k, v in st["nonchar"].items()},
        "emb": emb, "lm": None if st["lm"] is None else f"{CB.LM_NAME}@{CB.LM_REV[:8]}", "w": ctx.args.get("w", 0.005)},
        ensure_ascii=False), encoding="utf-8")
    return out


def _load(pred: Path) -> tuple[list[dict], dict]:
    return (json.loads((pred / "per.json").read_text(encoding="utf-8")),
            json.loads((pred / "meta.json").read_text(encoding="utf-8")))


def _pct(xs: list[dict], key: str, k: int) -> float | None:
    from ..cands_bench import pct
    return pct([x.get(key) for x in xs], k, len(xs)) if xs else None


# ───────────────────────── read-3c-cands ─────────────────────────

def run_3c(ctx: BenchCtx) -> Path:
    return _run(ctx, "3c", no_mlm=True)


def score_3c(ctx: BenchCtx, pred: Path) -> BenchResult:
    per, meta = _load(pred)
    m: dict = {"n_A": 0, "n_B": 0}
    for lay, pre in (("A", ""), ("B", "b_")):
        xs = [x for x in per if x["layer"] == lay]
        m[f"n_{lay}"] = len(xs)
        for k in KS3C:                                        # 3c＝glyph_candidate（r5 全字表＋异体族）金标在前 k 的 %
            m[f"{pre}recall_at_{k}"] = _pct(xs, "r_cand", k)
        m[f"{pre}r5_full_at_10"] = _pct(xs, "r_full", 10)     # 展开异体族之前（对照）
        m[f"{pre}frozen_3b_at_10"] = _pct(xs, "r_rare", 10)   # 现行产线 3b（对照；冻结）
    ext = [x for x in per if x["layer"] == "A" and x["st"].get("block") == "extB+"]
    m["extB_at_10"] = _pct(ext, "r_cand", 10)                 # 扩 B 以后的字：3b 升级档多数格不触发，这里看全字表的价值
    m["extB_n"] = len(ext)
    m["nonchar"] = meta["nonchar"]
    items = [{"id": x["id"], "layer": x["layer"], "ok": bool(x["r_cand"] and x["r_cand"] <= 10), "rank": x["r_cand"]}
             for x in per]
    return BenchResult("read-3c-cands", ctx.book, ctx.vols, m, "recall_at_10", items=items, n=len(per),
                       env={"emb": meta["emb"]})


# ───────────────────────── decide-4b-ctx ─────────────────────────

def run_4b(ctx: BenchCtx) -> Path:
    return _run(ctx, "3c,4b", no_mlm=False)


def score_4b(ctx: BenchCtx, pred: Path) -> BenchResult:
    per, meta = _load(pred)
    m: dict = {"n_A": 0, "n_B": 0}
    for lay, pre in (("A", ""), ("B", "b_")):
        xs = [x for x in per if x["layer"] == lay]
        ch = [x for x in xs if "r_chain" in x]               # 有前后文的格
        m[f"n_{lay}"] = len(xs)
        m[f"{pre}n_ctx"] = len(ch)
        for k in (1, 3, 10):                                  # 串联：池＝r5 前 200（并 3a 前 5），按「图像分＋w·logp」重排
            m[f"{pre}chain_top{k}"] = _pct(ch, "r_chain", k)
            m[f"{pre}img_top{k}"] = _pct(ch, "r_chain_img", k)  # 同一批格只看图像分（对照）
        if ch:
            m[f"{pre}gain_top1"] = round(m[f"{pre}chain_top1"] - m[f"{pre}img_top1"], 1)
        ctl = [x for x in ch if x["r_chain_img"] == 1]       # 伤害率：图像首位本来就对的格，重排后首位被挤掉的 %
        m[f"{pre}harm_rate"] = round(100.0 * sum(1 for x in ctl if x["r_chain"] != 1) / len(ctl), 2) if ctl else None
        fx = [x for x in xs if x.get("fixed_n") and "r_fixed_mlm" in x]    # 固定池（冻结的 3a 前 5 ∪ 3b）只比重排
        m[f"{pre}fixed_orig_top1"] = _pct(fx, "r_fixed", 1)
        m[f"{pre}fixed_mlm_top1"] = _pct(fx, "r_fixed_mlm", 1)
        miss = [x for x in ch if not (x["r_full"] and x["r_full"] <= 50)]  # 补字：图像前 50 没中的格里，补字命中几个
        m[f"{pre}extra_miss_n"] = len(miss)
        m[f"{pre}extra_hit_n"] = sum(1 for x in miss if x.get("extra_hit"))
    items = [{"id": x["id"], "layer": x["layer"], "ok": x.get("r_chain") == 1, "r_chain": x.get("r_chain"),
              "r_img": x.get("r_chain_img")} for x in per if "r_chain" in x]
    m["nonchar"] = meta["nonchar"]
    return BenchResult("decide-4b-ctx", ctx.book, ctx.vols, m, "chain_top1", items=items, n=len(items),
                       env={"emb": meta["emb"], "lm": meta["lm"], "w": meta["w"]})


# 护栏阈值取 2026-11-27 基线（dataset char-candidates/baseline.json 的 A 层三书最差值）再放宽：
# 3c：A 层 glyph_candidate 前 10 ≥93、前 50 ≥96（基线最差 史記 94.0／97.7）；
# 4b：串联首位 ≥75（基线最差 殿本 77.0）、融合不许比只看图差（gain_top1 ≥0，基线 +0.8～+6.7）、
# 伤害率 ≤6（基线最差 殿本 3.03；难格层 10.7 不进护栏，看报告）。
register(BenchSpec(
    id="read-3c-cands", title="第三步 3c 按图给候选（甲层难格召回 @1/10/30/50）",
    steps=("glyph_candidate",), owner="CV3", gold=GOLD, needs=("gold", "torch"), primary="recall_at_10",
    run=run_3c, score=score_3c, cost="light",
    guards=(Guard("recall_at_10", "min", 93.0), Guard("recall_at_50", "min", 96.0)),
    suites=("cands",),
    args={"limit": "只跑前 N 格（冒烟，缺省全部）"}))

register(BenchSpec(
    id="decide-4b-ctx", title="第四步 4b 按上下文重排与补字（串联首位、融合增益、伤害率）",
    steps=("context_rank",), owner="CV3", gold=GOLD, needs=("gold", "torch"), primary="chain_top1",
    run=run_4b, score=score_4b, cost="heavy",
    guards=(Guard("chain_top1", "min", 75.0), Guard("gain_top1", "min", 0.0), Guard("harm_rate", "max", 6.0)),
    suites=("cands",),
    args={"w": "融合权重（缺省 0.005＝产线）", "ctx_noise": "邻字加噪概率（缺省 0）", "limit": "只跑前 N 格（冒烟）"}))
