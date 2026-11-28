"""cut-2d：第二步切字整步（CV2 cut-bench，`eval/cut_bench.py`）接统一接口（CV0 2026-11-28 样板）。

资源（manager 备好，键见 `ctx.res`）：
- `gold`：dataset `char-segmentation/cut-bench/<短名>/`（bench.json＋每页 jsonl）；
- `ws`：书仓检出（`code/`，原图按册 yaml 的 `raw_dir` 放好金标涉及的页）；
- `data`：中心库数据目录（`books/`、`config/`、`corpus/`、`feedback/verdicts/char-segmentation/`）；
- `products`：产物包根（`<册>/border_detect/…`，第一步产物）；
- `data_home`（可选）：带 `.borrowed/group-*` 组配置的数据目录，跑时整份拷进工作目录。
跑法同 `cut_bench run`：冻结 → 只跑切字大步（不带人裁）→ `score_dir`。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from ..bench import BenchCtx, BenchResult, BenchSpec, Guard, register

#: dataset 里 cut-bench 的子目录名（短名）→ 书 id
GOLD = {"988g3f0wsu": "char-segmentation/cut-bench/shiji",
        "995ejelvk0": "char-segmentation/cut-bench/qtw",
        "96mid1ogzk": "char-segmentation/cut-bench/dianben",
        "99k3i35yww": "char-segmentation/cut-bench/maijing"}


def plan(gold: Path, book: str, vols: list) -> dict:
    meta = json.loads((Path(gold) / "bench.json").read_text(encoding="utf-8"))["vols"]
    return {v: [int(p) for p in x["pages"]] for v, x in meta.items() if not vols or v in vols}


def _vols(ctx: BenchCtx) -> dict:
    return {v: {"pages": p} for v, p in plan(Path(ctx.res["gold"]), ctx.book, ctx.vols).items()}


def run_env(pred: Path) -> dict:
    """在冻结出的工作区里跑 cv 的环境（切字大步、事后读产物的体检都用）：不在线问大模型，代码漂移只警告。"""
    env = {k: v for k, v in os.environ.items() if k not in ("GUJI_ANTHROPIC_API_KEY", "GUJI_LLM_ONLINE")}
    env.update(GUJI_WORKSPACE=str(pred / "ws"), GUJI_PRODUCTS_DIR=str(pred / "ws" / "products"),
               GUJI_CODE_DRIFT="warn", GUJI_DATA_HOME=str(pred / "datahome"), PYTHONIOENCODING="utf-8")
    return env


def run(ctx: BenchCtx) -> Path:
    from .. import cut_bench as CB
    gold = Path(ctx.res["gold"])
    short = gold.name
    bench_root = ctx.work / "bench"
    for vol, v in _vols(ctx).items():
        pages = (ctx.pages or {}).get(vol) or v["pages"]
        CB.freeze(Namespace(ws=ctx.res["ws"], data=ctx.res["data"], pack=ctx.res["products"], book=short, vol=vol,
                            pages=",".join(map(str, pages)), out=str(bench_root), gold_from=str(gold), overwrite=False))
    pred = ctx.work / "pred"
    if pred.exists():
        shutil.rmtree(pred)
    shutil.copytree(bench_root / short, pred / "ws", ignore=shutil.ignore_patterns("gold", "ref_products"))
    dh = pred / "datahome"
    if ctx.res.get("data_home") and (Path(ctx.res["data_home"]) / "main" / ".borrowed").exists():
        shutil.copytree(Path(ctx.res["data_home"]) / "main" / ".borrowed", dh / "main" / ".borrowed")
    env = run_env(pred)
    for vol, v in _vols(ctx).items():
        pages = (ctx.pages or {}).get(vol) or v["pages"]
        cmd = [sys.executable, "-m", "open_guji_cv", "pipeline", ctx.args.get("pipeline", "guji_default"), vol,
               "-w", str(pred / "ws"), "--from", "cut", "--to", "cut", "--pages", ",".join(map(str, pages)), "--force",
               "--no-pack", "--no-prep", "--allow-cv-mismatch", "--why", "bench cut-2d", "--allow-missing-deps"]
        if ctx.params:
            cmd += ["--params", json.dumps(ctx.params, ensure_ascii=False)]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        (ctx.work / f"run-{vol}.log").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
        if r.returncode:
            raise RuntimeError(f"{vol} 切字跑失败（日志 {ctx.work}/run-{vol}.log）：{r.stderr[-500:]}")
    return pred


def score(ctx: BenchCtx, pred: Path) -> BenchResult:
    from .. import cut_bench as CB
    short = Path(ctx.res["gold"]).name
    r = CB.score_dir(ctx.work / "bench" / short, pred / "ws" / "products")
    n = r["columns"] or 1
    m = {"col_exact": round(r["L2_col_exact"] / n, 4), "count_ok": round(r["L1_count_ok"] / n, 4),
         "kinds_ok": round(r["L1_kinds_ok"] / n, 4), "cell_F1": r["cell_F1"], "cell_P": r["cell_P"], "cell_R": r["cell_R"],
         "split": r["split"], "coarse_col_ok": round(r["coarse_cols"] / n, 4), "edge_dy_px": r["edge_dy_px"],
         "columns": r["columns"], "by_set": r["by_set"]}
    items = [{"id": k, "ok": bool(v["exact"]), **{a: v[a] for a in ("set", "origin", "n_gold", "n_pred", "count_ok", "split")}}
             for k, v in sorted(r["cols"].items())]
    return BenchResult("cut-2d", ctx.book, list(_vols(ctx)), m, "col_exact", items=items, n=r["columns"])


register(BenchSpec(
    id="cut-2d", title="第二步切字整步（列全对、字数全对、格 F1）", steps=("column_warp", "column_band", "column_end",
                                                                    "row_segment", "cell_shrink"),
    owner="CV2", gold=GOLD, needs=("gold", "config", "code", "raw", "products"), primary="col_exact",
    run=run, score=score, guards=(Guard("flip_worse", "max", 0),), suites=("cut",),
    args={"pipeline": "管线（缺省 guji_default）"}, plan=plan))
