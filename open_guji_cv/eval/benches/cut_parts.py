"""切字各小步的 bench（CV2，bench 统一接口 P1，2026-11-28）：都借 cut-2d 的跑法（冻结 cut-bench 页 → 只跑切字大步），
再用各自的打分器量同一份产物。

| bench | 量哪步 | 打分器 | 逐样本 |
|---|---|---|---|
| `cut-gate` | cut_gate 出口闸 | `cut_bench.gate_metrics`（以 2d 列全对为真值） | 列：闸的裁决对不对（坏列拦或旗、好列放行） |
| `cut-2e-frame` | 2e cell_shrink 列首列尾（2c 的结果） | `cut_frame`，分片 cut-frame | 格：IoU≥0.9 且不切笔不带渣 |
| `cut-2e-ink` | 2e cell_shrink 列中干净字 | `cut_frame --junk-tol 6`，分片 shrink-ink | 同上 |
| `cut-2b-band` | 2b column_band | `cut_ink.band_score`，分片 band-ink | 格：字身墨没被字带抹掉 |
| `cut-rulers` | 2d／2e 体检（R1–R4，无金标） | `eval/rulers.measure` | 无（只报数） |

金标目录 `ctx.res["gold"]` 都是 cut-bench 的这本书（`char-segmentation/cut-bench/<短名>/`，冻结与跑要用）；
各分片 items 在同一个测试集仓的兄弟目录 `char-segmentation/<分片>/items.jsonl`，按 `book`＝短名挑这本书。
分片的页都在 cut-bench 里（11-28 核过），只跑分片涉及的页。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .. import cut_frame as CF
from .. import cut_ink as CI
from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register
from . import cut as C

STEPS = ("column_warp", "column_band", "column_end", "row_segment", "cell_shrink")


def _shard(gold: Path, name: str) -> list[dict]:
    """cut-bench 金标目录 → 兄弟分片里这本书的 items（status ok／fixed）。"""
    f = Path(gold).parents[1] / name / "items.jsonl"
    short = Path(gold).name
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r.get("book") == short and r.get("status", "ok") in ("ok", "fixed")]


def _plan_from(name: str):
    def plan(gold: Path, book: str, vols: list) -> dict:
        out: dict = {}
        for r in _shard(gold, name):
            v = str(r["vol"])
            if not vols or v in vols:
                out.setdefault(v, set()).add(int(r["page"]))
        return {v: sorted(p) for v, p in out.items()}
    return plan


def _run_pages(plan):
    """cut-2d 的跑法，页只取本分片涉及的。"""
    def run(ctx: BenchCtx) -> Path:
        if ctx.pages is None:
            ctx.pages = plan(Path(ctx.res["gold"]), ctx.book, ctx.vols)
        return C.run(ctx)
    return run


def _products(pred: Path) -> Path:
    return pred / "ws" / "products"


# ---------------------------------------------------------------- cut-gate
def _gate_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    from .. import cut_bench as CB
    short = Path(ctx.res["gold"]).name
    r = CB.gate_metrics(ctx.work / "bench" / short, _products(pred))
    t = r["tiers"]
    m = {"any_recall": t["any"]["recall"], "any_false_alarm": t["any"]["false_alarm_rate"], "any_precision": t["any"]["precision"],
         "block_recall": t["block"]["recall"], "block_false_alarm": t["block"]["false_alarm_rate"],
         "bad": r["bad"], "good": r["good"], "columns": r["columns"], "pages_no_gate": len(r["pages_no_gate"]),
         "by_reason": r["by_reason"], "by_set": r["by_set"]}
    items = [{"id": k, "ok": v["bad"] == v["any"], "bad": v["bad"], "block": v["block"], "any": v["any"], "set": v["set"]}
             for k, v in sorted(r["cols"].items())]
    return BenchResult("cut-gate", ctx.book, list(ctx.vols), m, "any_recall", items=items, n=r["columns"])


register(BenchSpec(
    id="cut-gate", title="2 切字出口闸 cut_gate：坏列检出率、好列误报率（真值＝2d 列全对）", steps=("cut_gate",),
    owner="CV2", gold=C.GOLD, needs=("gold", "config", "code", "raw", "products"), primary="any_recall",
    run=C.run, score=_gate_score, guards=(Guard("flip_worse", "max", 0),), suites=("cut",), plan=C.plan))


# ---------------------------------------------------------------- 2e 紧框（cut-frame、shrink-ink）
def _frame_score(bench_id: str, shard: str, junk_tol: float | None):
    def score(ctx: BenchCtx, pred: Path) -> BenchResult:
        root = _products(pred)
        rows = [r for r in _shard(Path(ctx.res["gold"]), shard) if r.get("tight") and str(r["vol"]) in ctx.vols]
        r = CF.score(rows, CF.load_pred(root), 2.0, junk_tol, CF.load_cells(root))
        a = r["groups"].get("all") or {"cells": 0, "iou_ok": 0, "cut": 0, "junk": 0, "missing": 0, "misaligned": 0, "iou_sum": 0.0}
        n = a["cells"] or 1
        m = {"iou90": round(a["iou_ok"] / n, 4), "cut": a["cut"], "junk": a["junk"], "missing": a["missing"],
             "misaligned": a["misaligned"], "mean_iou": round(a["iou_sum"] / n, 4), "cells": a["cells"],
             "tol_px": r["tol"], "junk_tol_px": r["junk_tol"],
             "groups": {k: v for k, v in r["groups"].items() if k != "all"}}
        items = [{"id": k, "ok": bool(j["iou_ok"] and not j["cut"] and not j["junk"]),
                  **{x: j[x] for x in ("iou_ok", "cut", "junk", "missing", "misaligned", "iou")}}
                 for k, j in sorted(r["cells"].items())]
        return BenchResult(bench_id, ctx.book, list(ctx.vols), m, "iou90", items=items, n=a["cells"])
    return score


_P_FRAME, _P_INK, _P_BAND = _plan_from("cut-frame"), _plan_from("shrink-ink"), _plan_from("band-ink")
_GOLD2 = {k: v for k, v in C.GOLD.items() if v.endswith(("/shiji", "/qtw"))}       # 三个小分片只有史記、全唐文

register(BenchSpec(
    id="cut-2e-frame", title="2e 字框压缩·列首列尾紧框（不带框线、不切笔；2c 的结果）", steps=("column_end", "cell_shrink"),
    owner="CV2", gold=_GOLD2, needs=("gold", "config", "code", "raw", "products"), primary="iou90",
    run=_run_pages(_P_FRAME), score=_frame_score("cut-2e-frame", "cut-frame", None),
    guards=(Guard("flip_worse", "max", 0),), suites=("cut",), plan=_P_FRAME))

register(BenchSpec(
    id="cut-2e-ink", title="2e 字框压缩·列中干净字紧框（切笔／带渣，金标 v0.1 由人核格界＋连通域推出）", steps=("cell_shrink",),
    owner="CV2", gold=_GOLD2, needs=("gold", "config", "code", "raw", "products"), primary="iou90",
    run=_run_pages(_P_INK), score=_frame_score("cut-2e-ink", "shrink-ink", 6.0),
    guards=(Guard("flip_worse", "max", 0),), suites=("cut",), plan=_P_INK))


# ---------------------------------------------------------------- 2b 字带
def _band_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    rows = [r for r in _shard(Path(ctx.res["gold"]), "band-ink") if str(r["vol"]) in ctx.vols]
    r = CI.band_score(rows, _products(pred))
    a = r["groups"].get("all") or {"cols": 0, "cells": 0, "erase": 0, "erase_cols": 0, "missing": 0, "margin_px": {}}
    m = {"erase": a["erase"], "erase_cols": a["erase_cols"], "missing": a["missing"], "cells": a["cells"], "cols": a["cols"],
         "margin_median_px": a["margin_px"].get("median"), "margin_p10_px": a["margin_px"].get("p10"), "tol_px": r["tol"]}
    items = [{"id": k, "ok": not j["erase"] and not j["missing"], **j} for k, j in sorted(r["cells"].items())]
    return BenchResult("cut-2b-band", ctx.book, list(ctx.vols), m, "erase", items=items, n=a["cells"])


register(BenchSpec(
    id="cut-2b-band", title="2b 字带左右边：列中干净字的字身墨有没有被抹（金标 v0.1）", steps=("column_band",),
    owner="CV2", gold=_GOLD2, needs=("gold", "config", "code", "raw", "products"), primary="erase",
    run=_run_pages(_P_BAND), score=_band_score,
    guards=(Guard("erase", "max", 0), Guard("flip_worse", "max", 0)), suites=("cut",), plan=_P_BAND))


# ---------------------------------------------------------------- 体检：四把尺子（无金标）
_RULERS = """
import json, sys
from open_guji_cv.eval.rulers import measure
out = {}
for vol, pages in json.loads(sys.argv[1]).items():
    out[vol] = measure(vol, pages, full=True)
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def _rulers_score(ctx: BenchCtx, pred: Path) -> BenchResult:
    pages = {v: sorted(ps) for v, ps in (ctx.pages or C.plan(Path(ctx.res["gold"]), ctx.book, ctx.vols)).items()}
    r = subprocess.run([sys.executable, "-c", _RULERS, json.dumps(pages)], env=C.run_env(pred), capture_output=True,
                       text=True, check=False)
    if r.returncode:
        raise RuntimeError(f"rulers 失败：{r.stderr[-800:]}")
    res = json.loads(r.stdout.strip().splitlines()[-1])
    num: dict = {}
    hits: dict = {}                                  # 页 → {尺子: 命中数}
    for vol, x in res.items():
        for ru in x.get("rulers", []):
            a = num.setdefault(ru["key"], [0, 0])
            a[0] += ru["num"] or 0
            a[1] += ru["den"] or 0
            for d in ru.get("detail", []):
                h = hits.setdefault(f"{vol}:{d.get('page')}", {})
                h[ru["key"]] = h.get(ru["key"], 0) + 1
    m: dict = {k: (round(100.0 * a / b, 2) if b else None) for k, (a, b) in num.items()}
    m.update({f"{k}_num": a for k, (a, b) in num.items()})
    m.update({f"{k}_den": b for k, (a, b) in num.items()})
    items = [{"id": f"{v}:{p}", "ok": not hits.get(f"{v}:{p}"), **hits.get(f"{v}:{p}", {})}
             for v, ps in sorted(pages.items()) for p in ps]       # 逐页：哪把尺子命中几处（翻转＝页从干净变脏）
    return BenchResult("cut-rulers", ctx.book, list(ctx.vols), m, "R2", items=items, n=len(items))


register(BenchSpec(
    id="cut-rulers", title="切字体检四把尺子 R1–R4（R2 格线穿字、R3 首格上残墨、R4 紧框切字；无金标）", steps=STEPS,
    owner="CV2", gold=C.GOLD, needs=("gold", "config", "code", "raw", "products"), primary="R2",
    run=C.run, score=_rulers_score, guards=(Guard("flip_worse", "max", 0),), suites=("cut",), plan=C.plan))
