"""量线上外部大模型的**真实**正确率：拿 `context_decide.py` 线上调用日志
（`output/llm_online_calls/<book>.jsonl`）跟人审最终判定（`feedback/events.py`
的反馈事件日志）拼起来算。

跟离线评测（`scripts/eval_oracle_llm.py`）的区别：离线用教师强制的金标
上下文、跑的是固定答案表；这里用的是**处理每册时真实发生的线上调用**，
`context_after` 是弱近似（本列剩余字位的原始候选 top1，不是金标，见
`context_decide.py` 模块头【2026-09-10】），且样本量随日常处理量自然增长
——是「measure 正确率」要看的那个数，不是离线数字的替代品。

逻辑放包里（不是 `scripts/`），供 `scripts/measure_llm_online_accuracy.py`
（CLI）与控制台 `/api/llm_online_stats`（网页实时看）两处复用，同
`eval/rate_history.py` 的先例（`console/routers/evals.py` 模块头有过
「C2 之前反射进 scripts/ 是唯一一处、已改掉」的记录，不要再犯）。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_online_calls(log_dir: Path, book: str | None = None) -> list[dict]:
    """读全部（或指定 book 的）线上调用日志，按 (id) 去重取最后一条
    （同一字位可能因为重跑被问过不止一次，最近一次最能代表当前状态）。"""
    rows: dict[str, dict] = {}
    paths = ([log_dir / f"{book}.jsonl"] if book
            else sorted(log_dir.glob("*.jsonl")))
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = row["id"]
            prev = rows.get(key)
            if prev is None or row.get("ts", "") >= prev.get("ts", ""):
                rows[key] = row
    return list(rows.values())


def human_final_char(event) -> str | None:
    """`confirm`/`relabel` 事件的最终字——两种 payload 字段名都试
    （`feedback/consumers.py::glyphdb_admit` 同一套兼容写法，不重新发明口径）。"""
    if event.kind not in ("confirm", "relabel"):
        return None
    payload = event.payload
    c = payload.get("shape") or payload.get("char")
    if c and len(c) == 1:
        return c
    return None


def compute_report(log_dir: Path, book: str | None = None,
                   feedback_root: Path | None = None) -> dict[str, Any]:
    """核心聚合：日志 join 反馈事件 → 正确率报告（字典，CLI/API 共用）。

    只统计**已经有人审最终判定**的字位（`confirm`/`relabel` 事件）——
    没人审过的字位不计入分母，单独报「还没人审」条数，不能当作错的。
    """
    from ..feedback.events import EventLog

    rows = load_online_calls(log_dir, book)
    elog = EventLog(feedback_root) if feedback_root else EventLog()
    resolved = elog.resolve()

    n_total = len(rows)
    n_answered = sum(1 for r in rows if r.get("llm_answer_in_candidates"))
    n_resolved = n_correct = n_wrong = 0
    by_model: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    wrong_examples: list[dict] = []

    for r in rows:
        if not r.get("llm_answer_in_candidates"):
            continue      # 铁律 1：候选外答案没资格参与正确率——它本来就不会被采信
        ev = resolved.get(r["id"])
        final = human_final_char(ev) if ev else None
        if final is None:
            continue      # 还没人审到这个字位，不计入分母
        n_resolved += 1
        key = (r.get("provider", "?"), r.get("model", "?"))
        by_model[key][0] += 1
        ok = (r["llm_parsed_char"] == final)
        if ok:
            n_correct += 1
            by_model[key][1] += 1
        else:
            n_wrong += 1
            wrong_examples.append({"id": r["id"], "llm_said": r["llm_parsed_char"],
                                   "human_final": final,
                                   "candidates": r.get("candidates_chars")})

    return {
        "log_dir": str(log_dir), "book": book,
        "n_total_calls": n_total, "n_answered_in_candidates": n_answered,
        "n_resolved": n_resolved, "n_correct": n_correct, "n_wrong": n_wrong,
        "accuracy": round(n_correct / n_resolved, 4) if n_resolved else None,
        "by_model": {f"{p}/{m}": {"n": n, "correct": ok, "accuracy": round(ok / n, 4)}
                    for (p, m), (n, ok) in by_model.items()},
        "wrong_examples": wrong_examples,
    }
