"""near-form-admit：N01 形近字放行规则基准（GM3，2026-11-28）接统一接口。

原脚本 guji-manager `doc/参考/待审原因/near_form_guard/benchmark/score.py`：拿人裁过的格当金标，给几条「放行规则」打分，
看放行了多少格、错多少。规则只看（参校字、库首位、候选、类）的纯函数，放行字取参校字或库首位。
准确率守则：0 错且样本够，才可以考虑把规则做成放行通道。

资源：`gold`＝dataset `near-form-guard/<书id>/gold.tsv`（书、册、格、类、参校字、库首位、库候选前3、真字(人裁)…）。
只读、纯函数、不问大模型。参数：`--arg rule=R2`（主指标取这条规则，缺省 R2）。
指标：`wrong_admit`（主规则放错数）、`released`、`err_rate`、`ub95`（0 错时的 95% 上界，三之规则 3/n）、`rules`（各规则明细）。
护栏：`flip_worse` 为 0（同一份金标上，原先放对或没放的格不许变成放错）。
没有 `wrong_admit` 绝对线：现有各规则在殿本、全唐文都有错（见基线），没有一条规则已达到可放行，所以只守翻转。
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register

BOOKS = ("96mid1ogzk", "988g3f0wsu", "995ejelvk0")
#: 书 id → dataset 目录名（殿本真 id 是 96mid1ogzk；dataset 里目录沿用旧名 siku-zongmu，同 decide.py 的 DATASET_WS）
DATASET_WS = {"96mid1ogzk": "siku-zongmu"}
GOLD = {b: f"near-form-guard/{DATASET_WS.get(b, b)}" for b in BOOKS}
HARD = set("己已巳日曰")


def _tables():
    import collections
    from ...clustering.confusable import NEVER_MATCH_FAMILIES, partners
    fam = collections.defaultdict(set)
    for a, b in NEVER_MATCH_FAMILIES:
        fam[a].add(b)
        fam[b].add(a)
    return partners(), fam


def make_rules():
    P, FAM = _tables()

    def plain(ref):
        """参校字是 CJK 基本区常用字、不是己已巳日曰、自己没有形近伙伴。"""
        return bool(ref) and 0x3400 <= ord(ref[0]) <= 0x9FFF and ref not in HARD and not P.get(ref) and not FAM.get(ref)

    return {
        "R0": lambda r: r["参校字"],                                                      # 全部跟参校字
        "R1": lambda r: r["参校字"] if r["类"] == "B" else None,                           # 只 B 类跟参校字
        "R2": lambda r: r["参校字"] if r["类"] == "B" and plain(r["参校字"]) else None,     # B 类＋参校字平常
        "R3": lambda r: r["参校字"] if r["类"] in "BC" and plain(r["参校字"]) else None,   # B+C 类＋参校字平常
        "R4": lambda r: r["库首位"],                                                      # 全部跟库首位
    }


RULE_NOTE = {"R0": "全部跟参校字", "R1": "只 B 类跟参校字", "R2": "B 类＋参校字平常（排除〓/私用/己已巳日曰/有形近伙伴）",
             "R3": "B+C 类＋参校字平常", "R4": "全部跟库首位"}


def _rows(ctx: BenchCtx) -> list[dict]:
    p = Path(ctx.res["gold"]) / "gold.tsv"
    rows = list(csv.DictReader(open(p, encoding="utf-8"), delimiter="\t"))
    if ctx.vols:
        rows = [r for r in rows if r["册"] in ctx.vols]
    return rows


def plan(gold: Path, book: str, vols: list) -> dict:
    rows = csv.DictReader(open(Path(gold) / "gold.tsv", encoding="utf-8"), delimiter="\t")
    vs = sorted({r["册"] for r in rows})
    return {v: None for v in vs if not vols or v in vols}


def run(ctx: BenchCtx) -> Path:
    """read 模式：没有要跑的东西，把每条规则对每格的决定写成预测表。"""
    rules = make_rules()
    out = ctx.work / "pred.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for r in _rows(ctx):
            fh.write(json.dumps({"id": f"{r['册']}:{r['格']}", "truth": r["真字(人裁)"],
                                 **{k: f(r) for k, f in rules.items()}}, ensure_ascii=False) + "\n")
    return out


def score(ctx: BenchCtx, pred: Path) -> BenchResult:
    rule = ctx.args.get("rule", "R2")
    rows = [json.loads(l) for l in pred.read_text(encoding="utf-8").splitlines() if l.strip()]
    if rule not in RULE_NOTE:
        raise ValueError(f"rule 只有 {sorted(RULE_NOTE)}")
    rules = {}
    for k in RULE_NOTE:
        rel = [x for x in rows if x[k]]
        err = sum(1 for x in rel if x[k] != x["truth"])
        rules[k] = {"note": RULE_NOTE[k], "released": len(rel), "wrong": err,
                    "err_rate": round(err / len(rel), 4) if rel else None,
                    "ub95": round(3 / len(rel), 4) if rel and not err else None}
    m = rules[rule]
    metrics = {"rule": rule, "wrong_admit": m["wrong"], "released": m["released"], "err_rate": m["err_rate"],
               "ub95": m["ub95"], "rules": rules}
    items = [{"id": x["id"], "ok": not (x[rule] and x[rule] != x["truth"]), "released": x[rule], "truth": x["truth"]}
             for x in rows]
    return BenchResult("near-form-admit", ctx.book, ctx.vols, metrics, "wrong_admit", items=items, n=len(rows))


register(BenchSpec(
    id="near-form-admit", title="N01 形近字放行规则基准（放行格数、放错数、错率、0 错 95% 上界）",
    steps=("near_form_guard",), owner="GM3", gold=GOLD, needs=("gold",), primary="wrong_admit",
    run=run, score=score, mode="read", cost="light", guards=(Guard("flip_worse", "max", 0),),
    suites=("text",), item_key="id", item_ok="ok", plan=plan,
    args={"rule": "R0–R4（缺省 R2）：主指标取哪条放行规则"}))
