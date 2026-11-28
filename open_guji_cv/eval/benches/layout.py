"""第一步版面三个 bench 接统一接口（CV1，2026-11-28，P1）。

| id | 小步 | 量什么 | 金标（dataset） |
|---|---|---|---|
| `layout` | 1b 版框界行（`border_detect`＋闸） | 界行偏差（≤5px 算准）、漏线多线、框、列数、页型 | `layout/items.jsonl`（79 页，按册别名分书） |
| `page-survey` | 1a 页面预检（尺寸异常页） | 异常页召回／精确率、形态；正常页判异常必须为 0 | `page-survey/items.jsonl`（种子，rule 快照） |
| `seal-box` | 1c 印章定位 | 印章框 IoU 召回／精确率；漏认必须为 0 | `seal-box/items.jsonl`（只有待核底稿＝no_gold） |

金标按「册别名」存页（`vol01`、`sj05`、`qtw005`、`mj01`），一份文件覆盖四套书；这里按书 id（工作区 id）取各自的
别名并换回真册号（`vol01`→`vol01`，`sj05`→`05`，`qtw005`→`005`，`mj01`→`1`）。三个 bench 的 `plan` 只给金标涉及的页，
manager 只取这些原图。`layout`、`seal-box` 在书仓里按册 yaml 现跑第一大步（`--from layout --to layout`），产物写进
工作目录，不动正式产物；`page-survey` 的输入冻结在金标里（尺寸），不需要图。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .. import layout_bench as lb
from .. import layout_metrics as lm
from .. import seal_bench as sb
from .. import survey_bench as vb
from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register

#: 书 id（工作区 id）→ 金标册别名前缀
PREFIX = {"siku-zongmu": "vol", "988g3f0wsu": "sj", "995ejelvk0": "qtw", "99k3i35yww": "mj"}


def vol_of(alias: str) -> str:
    """金标册别名 → 真册号。"""
    if alias.startswith("vol"):
        return alias
    for pre in ("sj", "qtw", "mj"):
        if alias.startswith(pre):
            n = alias[len(pre):]
            return str(int(n)) if pre == "mj" and n.isdigit() and int(n) < 2 else n
    return alias


def _read(gold: Path) -> list[dict]:
    return [json.loads(l) for l in Path(gold).read_text(encoding="utf-8").splitlines() if l.strip()]


def _items(gold, book: str, vols=None, human_only: bool = False) -> list[dict]:
    pre = PREFIX.get(book)
    out = []
    for it in _read(gold):
        a = it["anchor"]
        if pre is None or not a["book"].startswith(pre) or it.get("status", "active") != "active":
            continue
        if human_only and it.get("label_origin", "human") != "human":
            continue
        if vols and vol_of(a["book"]) not in vols:
            continue
        out.append(it)
    return out


def _plan(gold: Path, book: str, vols: list, human_only: bool = False) -> dict:
    out: dict[str, set] = {}
    for it in _items(gold, book, vols, human_only):
        out.setdefault(vol_of(it["anchor"]["book"]), set()).add(int(it["anchor"]["page"]))
    return {v: sorted(p) for v, p in out.items()}


def plan_layout(gold: Path, book: str, vols: list) -> dict:
    return _plan(gold, book, vols)


def plan_seal(gold: Path, book: str, vols: list) -> dict:
    return _plan(gold, book, vols, human_only=True)       # 只有待核底稿＝没金标，manager 报 no_gold


def _run_layout(ctx: BenchCtx, plan: dict) -> Path:
    """在书仓里对金标页现跑第一大步，产物写到 `<work>/pred/products`（`GUJI_PRODUCTS_DIR`），不动正式产物。"""
    pred = ctx.work / "pred"
    (pred / "products").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "GUJI_LLM_ONLINE")}
    env.update(GUJI_WORKSPACE=str(ctx.res["ws"]), GUJI_PRODUCTS_DIR=str(pred / "products"),
               GUJI_CODE_DRIFT="warn", PYTHONIOENCODING="utf-8")
    if ctx.res.get("data_home"):
        env["GUJI_DATA_HOME"] = str(ctx.res["data_home"])
    for vol, pages in plan.items():
        cmd = [sys.executable, "-m", "open_guji_cv", "pipeline", ctx.args.get("pipeline", "guji_default"), vol,
               "-w", str(ctx.res["ws"]), "--from", "layout", "--to", "layout", "--pages", ",".join(map(str, pages)),
               "--force", "--no-pack", "--allow-cv-mismatch", "--why", "bench layout", "--allow-missing-deps"]
        if ctx.params:
            cmd += ["--params", json.dumps(ctx.params, ensure_ascii=False)]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        (ctx.work / f"run-{vol}.log").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
        if r.returncode:
            raise RuntimeError(f"{vol} 版面跑失败（日志 {ctx.work}/run-{vol}.log）：{r.stderr[-500:]}")
    return pred


# ───────────────────────── layout（1b）─────────────────────────

def run_layout(ctx: BenchCtx) -> Path:
    return _run_layout(ctx, _plan(Path(ctx.res["gold"]), ctx.book, ctx.vols))


def score_layout(ctx: BenchCtx, pred: Path) -> BenchResult:
    products = pred / "products"
    per, items, missing = [], [], []
    for it in _items(ctx.res["gold"], ctx.book, ctx.vols):
        a = it["anchor"]
        key = f"{a['book']}:{a['page']}"
        d = lb.pred_doc(products, vol_of(a["book"]), int(a["page"]))
        if d is None:
            missing.append(key)
            items.append({"id": key, "ok": False, "missing": True})
            continue
        r = lm.page_metrics(dict(it["expected"], book=a["book"], stratum=it.get("stratum")), d)
        per.append((key, r))
        v = r.get("vlines") or {}
        p95 = v.get("line_p95", [])
        miss = v.get("n_gold", 0) - v.get("n_matched", 0)
        pol = r.get("policy") or {}
        items.append({"id": key, "ok": miss == 0 and not any(x > 5 for x in p95) and not pol.get("wrong_skip"),
                      "lines_missed": miss, "lines_gt5": sum(x > 5 for x in p95),
                      "p95_max": round(max(p95), 1) if p95 else None, "wrong_skip": bool(pol.get("wrong_skip"))})
    if not per:
        return BenchResult("layout", ctx.book, ctx.vols, {}, "line_ok_rate", items=items, status="failed",
                           reason=f"金标页都没有产物：{missing[:5]}")
    a = lb.summarize_recs(per)
    gold_lines = a["lines_gold"]
    gt5 = a["line_gt_px"][">5"]
    ok_lines = a["lines_matched"] - gt5
    pol = a.get("policy") or {}
    fr = a.get("frame") or {}
    m = {"line_ok_rate": round(ok_lines / gold_lines, 4) if gold_lines else None,
         "recall@0.05": a.get("recall@0.05"), "lines_gold": gold_lines,
         "lines_missed": gold_lines - a["lines_matched"], "lines_extra": a["lines_pred"] - a["lines_matched"],
         "lines_gt5px": gt5, "lines_gt10px": a["line_gt_px"][">10"], "lines_gt20px": a["line_gt_px"][">20"],
         "top_frame_p95_px": (a.get("top_frame_px") or {}).get("p95"),
         "bottom_frame_p95_px": (a.get("bottom_frame_px") or {}).get("p95"),
         "frame_kind_acc": fr.get("kind_acc"), "n_cols_acc": a.get("n_cols_acc"),
         "policy_acc": pol.get("acc"), "wrong_skip": pol.get("wrong_skip", 0), "wrong_keep": pol.get("wrong_keep", 0),
         "pages": a["pages"], "pages_missing": len(missing), "worst": a["worst"]}
    return BenchResult("layout", ctx.book, ctx.vols, m, "line_ok_rate", items=items, n=len(items))


# ───────────────────────── page-survey（1a）─────────────────────────

def run_survey(ctx: BenchCtx) -> Path:
    return ctx.work                                         # 输入冻结在金标里，没有要跑的


def score_survey(ctx: BenchCtx, pred: Path) -> BenchResult:
    its = _items(ctx.res["gold"], ctx.book, ctx.vols)
    rep = vb.run(its)
    flips = set(rep["flips"])
    items = [{"id": r["key"], "ok": r["gold_odd"] == r["pred_odd"] and r["gold_kind"] == r["pred_kind"],
              "origin": r["origin"], "gold_odd": r["gold_odd"], "pred_odd": r["pred_odd"]} for r in rep["rows"]]
    rows = rep["rows"]
    tp = sum(r["gold_odd"] and r["pred_odd"] for r in rows)
    fn = sum(r["gold_odd"] and not r["pred_odd"] for r in rows)
    fp = sum((not r["gold_odd"]) and r["pred_odd"] for r in rows)
    m = {"agree": round(1 - len(flips) / len(rows), 4) if rows else None, "pages": len(rows),
         "gold_odd": tp + fn, "recall": tp / (tp + fn) if tp + fn else None,
         "precision": tp / (tp + fp) if tp + fp else None, "false_alarm": fp, "missed_odd": fn,
         "human_labels": sum(r["origin"] == "human" for r in rows), "skipped_books": rep["skipped_books"]}
    reason = "" if m["human_labels"] else "金标全是 rule 快照（无人核），只能当回归"
    return BenchResult("page-survey", ctx.book, ctx.vols, m, "agree", items=items, n=len(items), reason=reason)


# ───────────────────────── seal-box（1c）─────────────────────────

def run_seal(ctx: BenchCtx) -> Path:
    return _run_layout(ctx, _plan(Path(ctx.res["gold"]), ctx.book, ctx.vols, human_only=True))


def score_seal(ctx: BenchCtx, pred: Path) -> BenchResult:
    thr = float(ctx.args.get("iou", 0.5))
    its = _items(ctx.res["gold"], ctx.book, ctx.vols, human_only=True)
    rep = sb.run(pred / "products", [dict(i, anchor={"book": vol_of(i["anchor"]["book"]), "page": i["anchor"]["page"]})
                                     for i in its], thr)
    s = rep["summary"].get("全部") or {}
    m = {f"recall@iou{thr}": s.get(f"recall@iou{thr}"), f"precision@iou{thr}": s.get(f"precision@iou{thr}"),
         "iou_median": s.get("iou_median"), "kind_acc": s.get("kind_acc"), "gold_seals": s.get("gold_seals", 0),
         "missed_seals": len(s.get("missed_seals", [])), "extra_seals": len(s.get("extra_seals", [])),
         "pages": s.get("pages", 0)}
    missed = set(x.rsplit("#", 1)[0] for x in s.get("missed_seals", []))
    items = [{"id": f"{i['anchor']['book']}:{i['anchor']['page']}",
              "ok": f"{vol_of(i['anchor']['book'])}:{i['anchor']['page']}" not in missed} for i in its]
    return BenchResult("seal-box", ctx.book, ctx.vols, m, f"recall@iou{thr}", items=items, n=len(items))


_G = {ws: "layout/items.jsonl" for ws in PREFIX}
register(BenchSpec(
    id="layout", title="1b 版框界行（界行偏差、框、列数、页型）", steps=("border_detect", "border_detect_gate"),
    owner="CV1", gold=_G, needs=("gold", "config", "code", "raw"), primary="line_ok_rate",
    run=run_layout, score=score_layout, guards=(Guard("wrong_skip", "max", 0), Guard("flip_worse", "max", 0)),
    suites=("layout",), args={"pipeline": "管线（缺省 guji_default）"}, plan=plan_layout))

register(BenchSpec(
    id="page-survey", title="1a 页面预检（尺寸异常页）", steps=("page_survey",),
    owner="CV1", gold={ws: "page-survey/items.jsonl" for ws in PREFIX}, needs=("gold",), primary="agree",
    run=run_survey, score=score_survey, guards=(Guard("false_alarm", "max", 0), Guard("flip_worse", "max", 0)),
    suites=("layout",), plan=lambda gold, book, vols: _plan(gold, book, vols)))

register(BenchSpec(
    id="seal-box", title="1c 印章定位（框 IoU）", steps=("seal_detect",),
    owner="CV1", gold={ws: "seal-box/items.jsonl" for ws in PREFIX}, needs=("gold", "config", "code", "raw"),
    primary="recall@iou0.5", run=run_seal, score=score_seal,
    guards=(Guard("missed_seals", "max", 0), Guard("flip_worse", "max", 0)),
    suites=("layout",), args={"iou": "IoU 门限（缺省 0.5）", "pipeline": "管线（缺省 guji_default）"}, plan=plan_seal))
