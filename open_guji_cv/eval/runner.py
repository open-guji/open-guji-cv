"""跑一个评测器：子进程 → 抓 stdout → 解析指标 → 补金标状态 → 统一报告。

金标状态（`n_gold` / `stale_gold` / `uncertain_skipped`）**由 GoldStore 提供**，
不指望评测脚本自己报——它们读的是旧文件，压根不知道 stale 这回事。
这样「先查漂移再谈数字」就成了报告的固有部分，而不是靠人记得去查。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .registry import EvalSpec, find_eval, runnable
from .report import EvalReport, Metric, parse_metrics


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def run_eval(key: str, dataset_root: Path | None = None, timeout: int = 900,
             allow: tuple[str, ...] = ("products",),
             report_dir: Path | None = None) -> EvalReport:
    spec = find_eval(key)
    if spec is None:
        return EvalReport(eval_id=key, shard="", status="failed", error=f"没有这个评测器: {key}")

    from ..gold.store import GoldStore
    store = GoldStore(dataset_root)
    ds = store.root

    rep = EvalReport(eval_id=spec.id, shard=spec.shard)
    ok, why = runnable(spec, allow)
    if not ok:
        rep.status = "skipped"
        rep.error = why
        _fill_gold(rep, store, spec)
        return rep

    target = spec.target(ds)
    if target is not None and not target.exists():
        rep.status = "skipped"
        rep.error = f"金标路径不存在: {target}"
        return rep

    out_path = None
    if spec.out_flag:
        d = report_dir or (repo_root() / "runs" / "evals")
        d.mkdir(parents=True, exist_ok=True)
        out_path = d / f"{spec.id}.json"

    argv = spec.argv(ds, out_path)
    rep.command = " ".join(argv)
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    if spec.pythonpath:
        env["PYTHONPATH"] = str(repo_root()) + os.pathsep + env.get("PYTHONPATH", "")

    # 跑之前记下数据集仓里那个 report.json 在不在——只清本次新产生的
    stray_before = (ds / spec.shard / "report.json").exists() if spec.out_flag else None

    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=repo_root(), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = (p.stdout or "") + (("\n" + p.stderr) if p.returncode and p.stderr else "")
        rep.exit_code = p.returncode
    except subprocess.TimeoutExpired:
        rep.status, rep.error, rep.elapsed = "failed", f"超时（{timeout}s）", time.time() - t0
        return rep
    except Exception as e:   # noqa: BLE001
        rep.status, rep.error, rep.elapsed = "failed", f"{type(e).__name__}: {e}", time.time() - t0
        return rep
    rep.elapsed = round(time.time() - t0, 2)
    rep.stdout_tail = "\n".join(out.strip().splitlines()[-25:])

    # 有的脚本 --out 默认值指向数据集仓（context_correction / char_ocr 的
    # `root / "report.json"`），不传就往那儿写、污染工作区。
    # **只删本次跑之前不存在的那个文件**——好几个分片的 report.json 是仓库里
    # 跟踪着的历史基线，删掉就把基线弄丢了（第一版防护就是这么删过头的）。
    if spec.out_flag and stray_before is not None and not stray_before:
        stray = ds / spec.shard / "report.json"
        if stray.exists() and (out_path is None or stray != out_path):
            try:
                stray.unlink()
                rep.stdout_tail += f"\n[适配层] 清掉脚本新写进数据集仓的 {stray.name}"
            except OSError:
                pass

    # 退出码不可靠：好几个脚本缺产物时 print 完就 return，退出码仍是 0；
    # 反过来也有脚本把指标印完了才在收尾处崩（left_cut 的除零）。
    # 所以判据是「有没有解析出指标」，退出码只作参考。
    rep.metrics = parse_metrics(out)
    if out_path and out_path.exists():
        try:
            rep.metrics = _merge_json_metrics(rep.metrics, json.loads(out_path.read_text(encoding="utf-8")))
        except Exception:   # noqa: BLE001
            pass

    gate = _gate_verdict(out)
    if gate:
        rep.gate = gate
    if rep.metrics or gate:
        # **回归门的结论本身就是结果**：印了「回归门：通过」而没有别的数字，
        # 也是跑成功了（这类闸的产出就是过没过）。失败同理——门拦住了东西，
        # 跟门本身坏掉是两回事，混报会让人分不清该看算法还是该修评测。
        rep.status = "regressed" if gate == "失败" else "ok"
        if gate and not rep.metrics:
            rep.metrics = [Metric(name="回归门", value=gate)]
        if rep.exit_code not in (0, None):
            rep.error = f"脚本以 {rep.exit_code} 退出（结果已产出，多为收尾处报错）：" \
                        + (rep.stdout_tail.splitlines() or [""])[-1][:120]
    elif rep.exit_code not in (0, None):
        rep.status, rep.error = "failed", (rep.stdout_tail.splitlines() or [""])[-1][:200]
    else:
        rep.status = "failed"
        rep.error = "没有解析出任何指标（多半是缺产物：" + (rep.stdout_tail.splitlines() or [""])[-1][:120] + "）"

    _fill_gold(rep, store, spec)
    return rep


# 三种写法都要认（实测）：
#   回归门：通过        多数
#   回归门：**失败**    失败态带星号包裹，通过态不带——不对称
#   回归门：31/31 通过  eval_normalize 独有，中间夹分数
_GATE = re.compile(r"回归门[:：]\s*(?:\*\*)?\s*(?:\d+\s*/\s*\d+\s*)?(通过|失败)")


def _gate_verdict(text: str) -> str:
    """抓「回归门：通过 / 失败」。这是评测结论，与脚本跑没跑起来无关。"""
    hits = _GATE.findall(text)
    return "失败" if "失败" in hits else ("通过" if hits else "")


def _fill_gold(rep: EvalReport, store, spec: EvalSpec) -> None:
    """金标状态由 GoldStore 报，评测脚本不知道 stale 这回事。"""
    try:
        items = store.list(spec.shard)
    except Exception:   # noqa: BLE001
        return
    if not items:
        return
    rep.n_gold = len(items)
    rep.stale_gold = sum(1 for i in items if i.status == "stale")
    rep.uncertain_skipped = sum(1 for i in items if i.status == "uncertain")


_NUM_KEYS = ("accuracy", "recall", "precision", "f1", "rate", "acc", "mean", "median",
             "pass", "ok", "match", "iou", "err", "diff", "score")


def _merge_json_metrics(existing: list[Metric], data: dict, limit: int = 12) -> list[Metric]:
    """报告 JSON 里的数字指标并进来。

    有的脚本（normalize 等）把结果全写进 JSON、stdout 只印一行文件路径，
    这时 JSON 是唯一的指标来源，不能因为 stdout 没数就判失败。
    """
    if not isinstance(data, dict):
        return existing
    have = {m.name for m in existing}
    out = list(existing)

    def take(prefix: str, d: dict) -> None:
        for k, v in d.items():
            if len(out) >= limit:
                return
            name = f"{prefix}{k}"
            if name in have or isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and any(t in k.lower() for t in _NUM_KEYS):
                out.append(Metric(name=name, value=round(float(v), 4)))
                have.add(name)

    take("", data)
    # 常见嵌套：{"summary": {...}} / {"overall": {...}} / {"baseline": {...}}
    for key in ("summary", "overall", "totals", "baseline", "report"):
        if isinstance(data.get(key), dict):
            take("", data[key])
    for dk in ("n", "total", "n_samples", "count", "n_gold"):
        if isinstance(data.get(dk), int):
            for m in out:
                if m.denominator is None:
                    m.denominator = data[dk]
            break
    return out


def run_many(keys: list[str], **kw) -> list[EvalReport]:
    return [run_eval(k, **kw) for k in keys]
