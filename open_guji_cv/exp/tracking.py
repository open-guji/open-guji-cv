# -*- coding: utf-8 -*-
"""跨实验记录层：把每份报告记进 MLflow，本地 `guji exp ui`（= `mlflow ui`）翻看、勾几次跑做对比图。

可选依赖（`pip install -e ".[exp]"`）：没装就跳过，`report.md` 照出——统计与判准都在 `compare`，
MLflow 只是账本与看板（用户 10-07 定用 MLflow，overview#457）。

记法：

- **存储**：纯本地文件，不要服务器。缺省 `<实验根>/mlflow.db`（sqlite）+ `<实验根>/mlartifacts/`；
  设了 `MLFLOW_TRACKING_URI` 就用它。
- **MLflow 实验 = 我们的实验名**（`shadow_veto-vol05`）。每出一次报告记：
  - 一个**父 run**（`<实验名> @ <code_rev>`）：参数是书、快照、步段、判对口径；附件是 report.md/json、
    charts/、翻转审查页、exp.yaml、labels.jsonl；
  - 每个变体一个**子 run**（基线也是）：参数 = 实际跑的参数（`seed_admit.shadow_conf` 这样拍平），
    指标 = 各范围的放行率/送审率/排除率/放行错误率；非基线再加与基线的差、95% CI 两端、翻转计数、
    判准达标数。
- **同一实验目录重出报告，先删旧 run**（tag `guji.exp_dir`），看板上永远是最新一份，不堆重复。
"""
from __future__ import annotations

import os
from pathlib import Path

from .compare import FLIP_KEYS, METRICS

# mlflow 一 import 就打一条「去加载某 skill」的提示；对我们是噪声
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

TAG_DIR = "guji.exp_dir"
TAG_KIND = "guji.kind"
_FLIP_SUBKEYS = {"admit_to_review": ("caught", "wrongly_blocked"), "review_to_admit": ("admit_ok", "admit_err"),
                 "char_changed": ("a_ok_b_err", "a_err_b_ok", "both_err")}


def available() -> bool:
    try:
        import mlflow  # noqa: F401
    except ImportError:
        return False
    return True


def tracking_uri(root: Path) -> str:
    return os.environ.get("MLFLOW_TRACKING_URI") or f"sqlite:///{Path(root).resolve() / 'mlflow.db'}"


def _flat(params: dict[str, dict]) -> dict[str, str]:
    return {f"{sid}.{k}": str(v) for sid, kv in sorted(params.items()) for k, v in sorted(kv.items())}


def _variant_metrics(rep: dict, vn: str) -> dict[str, float]:
    """一个变体的指标。基线取任一比较块的 A 侧；非基线取自己比较块的 B 侧，外加差值、CI、翻转、判准。"""
    out: dict[str, float] = {}
    comps = rep["comparisons"]
    if vn == rep["base"]:
        comp = next(iter(comps.values()), None)
        side = "A"
    else:
        comp, side = comps[vn], "B"
    if comp is None:
        return out
    for sc, blk in comp["overall"].items():
        out[f"{sc}.cells"] = blk["cells"]
        for m in METRICS:
            b = blk[m]
            if b[side] is not None:
                out[f"{sc}.{m}"] = b[side]
            if side == "B" and b["diff"] is not None:
                out[f"{sc}.{m}.diff"] = b["diff"]
                if b["ci"]:
                    out[f"{sc}.{m}.ci_lo"], out[f"{sc}.{m}.ci_hi"] = b["ci"]
    if side == "B":
        for k in FLIP_KEYS:
            f = comp["flips"][k]
            out[f"flips.{k}"] = f["n"]
            out[f"flips.{k}.labeled"] = f["labeled"]
            for sub in _FLIP_SUBKEYS.get(k, ()):
                out[f"flips.{k}.{sub}"] = f[sub]
        g = comp["guardrails"]
        out["guardrails.pass"] = sum(x["verdict"] == "pass" for x in g)
        out["guardrails.fail"] = sum(x["verdict"] == "fail" for x in g)
        out["guardrails.unknown"] = sum(x["verdict"] in ("unknown", "error") for x in g)
        for name, r in comp["mcnemar"].items():
            if r["p"] is not None:
                out[f"mcnemar.{name}.p"] = r["p"]
    return {k: float(v) for k, v in out.items()}


def log_report(edir: str | Path, rep: dict, state: dict | None = None, *, root: str | Path | None = None) -> dict | None:
    """记一份报告。没装 mlflow 返回 None。返回 {uri, experiment_id, parent_run_id, runs}。"""
    if not available():
        return None
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    from mlflow.tracking import MlflowClient

    edir = Path(edir).resolve()
    root = Path(root).resolve() if root else edir.parent
    uri = tracking_uri(root)
    client = MlflowClient(tracking_uri=uri)
    exp = client.get_experiment_by_name(rep["name"])
    if exp is None:
        art = (root / "mlartifacts" / rep["name"]).resolve()
        art.mkdir(parents=True, exist_ok=True)
        exp_id = client.create_experiment(rep["name"], artifact_location=art.as_uri())
    else:
        exp_id = exp.experiment_id
    for old in client.search_runs([exp_id], filter_string=f"tags.`{TAG_DIR}` = '{edir}'", max_results=1000):
        client.delete_run(old.info.run_id)

    code = rep.get("code_rev") or "?"
    tags = {TAG_DIR: str(edir), "guji.books": ",".join(rep["books"]), "guji.code_rev": code,
            "guji.match": rep.get("match", "exact")}
    parent = client.create_run(exp_id, run_name=f"{rep['name']} @ {code}", tags={**tags, TAG_KIND: "report"})
    pid = parent.info.run_id
    cfg = (state or {}).get("config") or {}
    for k, v in {"books": ",".join(rep["books"]), "steps": "→".join(rep["steps"]), "snapshot": rep.get("snapshot"),
                 "match": rep.get("match", "exact"), "book_params": rep.get("book_params", "keep"),
                 "base": rep["base"], "variants": ",".join(rep["comparisons"]), "bootstrap": rep["bootstrap"],
                 "seed": rep["seed"], "pages": cfg.get("pages")}.items():
        client.log_param(pid, k, str(v))
    for name in ("report.md", "report.json", "exp.yaml", "labels.jsonl", "labels_extra.jsonl"):
        if (edir / name).exists():
            client.log_artifact(pid, str(edir / name))
    for sub in ("charts", "flips"):
        if (edir / sub).is_dir():
            client.log_artifacts(pid, str(edir / sub), artifact_path=sub)

    runs = {}
    eff = rep.get("effective_params") or {}
    for vn in [rep["base"], *rep["comparisons"]]:
        r = client.create_run(exp_id, run_name=vn,
                              tags={**tags, TAG_KIND: "variant", "mlflow.parentRunId": pid,
                                    "guji.variant": vn, "guji.is_base": str(vn == rep["base"])})
        rid = r.info.run_id
        per_book = eff.get(vn) or {}
        books = sorted(per_book)
        if not books:                       # 老实验没记实际参数：退回「评测口径 ∪ 变体覆盖」
            from .config import merge_params
            flat = _flat(merge_params(rep.get("eval_params"), rep["params"].get(vn)))
        elif len({str(per_book[b]) for b in books}) == 1:
            flat = _flat(per_book[books[0]])
        else:
            flat = {f"{b}.{k}": v for b in books for k, v in _flat(per_book[b]).items()}
        for k, v in flat.items():
            client.log_param(rid, k, v[:6000])
        for k, v in _variant_metrics(rep, vn).items():
            client.log_metric(rid, k, v)
        client.set_terminated(rid)
        runs[vn] = rid
    client.set_terminated(pid)
    return {"uri": uri, "experiment_id": exp_id, "parent_run_id": pid, "runs": runs}


def ui_command(root: str | Path, port: int = 5000) -> list[str]:
    import sys
    return [sys.executable, "-m", "mlflow", "ui", "--backend-store-uri", tracking_uri(Path(root)),
            "--host", "127.0.0.1", "--port", str(port)]
