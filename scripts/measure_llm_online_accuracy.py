"""量线上外部大模型的**真实**正确率：拿 `context_decide.py` 线上调用日志
（`output/llm_online_calls/<book>.jsonl`）跟人审最终判定（`feedback/events.py`
的反馈事件日志）拼起来算。

跟离线评测（`scripts/eval_oracle_llm.py`）的区别：离线用教师强制的金标
上下文、跑的是固定答案表；这里用的是**处理每册时真实发生的线上调用**，
`context_after` 是弱近似（本列剩余字位的原始候选 top1，不是金标，见
`context_decide.py` 模块头【2026-09-10】），且样本量随日常处理量自然增长
——是「measure 正确率」要看的那个数，不是离线数字的替代品。

用法：
    PYTHONPATH=. python scripts/measure_llm_online_accuracy.py \\
        --log-dir output/llm_online_calls

只统计**已经有人审最终判定**的字位（`confirm`/`relabel` 事件）——没人审
过的字位不计入分母，会单独报「还没人审」的条数，不能当作错的。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_online_calls(log_dir: Path, book: str | None) -> list[dict]:
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
    （`consumers.py::glyphdb_admit` 同一套兼容写法，不重新发明口径）。"""
    if event.kind not in ("confirm", "relabel"):
        return None
    payload = event.payload
    c = payload.get("shape") or payload.get("char")
    if c and len(c) == 1:
        return c
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(REPO / "output" / "llm_online_calls"))
    ap.add_argument("--book", default=None, help="只看这本书；默认全部")
    ap.add_argument("--feedback-root", default=None,
                    help="反馈事件根目录；默认 EventLog 的 default_feedback_root()")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from open_guji_cv.feedback.events import EventLog

    log_dir = Path(args.log_dir)
    rows = load_online_calls(log_dir, args.book)
    if not rows:
        print(f"没有线上调用日志（{log_dir}），还没在真实处理里开过 "
             "enable_online_llm，或者书名/路径不对")
        return

    elog = EventLog(Path(args.feedback_root)) if args.feedback_root else EventLog()
    resolved = elog.resolve()   # {target.key: 最终事件}，跨全部 batch

    n_total = len(rows)
    n_answered = sum(1 for r in rows if r.get("llm_answer_in_candidates"))
    n_resolved = n_correct = n_wrong = 0
    by_model: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])  # [resolved, correct]
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

    print(f"线上调用总数: {n_total}（候选内命中: {n_answered}）")
    print(f"已有人审最终判定可比对: {n_resolved}（还没人审: "
         f"{n_answered - n_resolved}——这些不计入正确率，不是错）")
    if n_resolved:
        print(f"线上正确率: {n_correct}/{n_resolved} = {n_correct / n_resolved:.2%}")
        print(f"\n{'provider/model':<24} {'n':>6} {'正确率':>8}")
        for (prov, model), (n, ok) in sorted(by_model.items()):
            print(f"{prov + '/' + model:<24} {n:>6} {ok / n:>7.2%}")
    else:
        print("一条人审判定都还没对上——太早，先攒量")

    report = {"log_dir": str(log_dir), "book": args.book,
             "n_total_calls": n_total, "n_answered_in_candidates": n_answered,
             "n_resolved": n_resolved, "n_correct": n_correct, "n_wrong": n_wrong,
             "accuracy": round(n_correct / n_resolved, 4) if n_resolved else None,
             "by_model": {f"{p}/{m}": {"n": n, "correct": ok, "accuracy": round(ok / n, 4)}
                         for (p, m), (n, ok) in by_model.items()},
             "wrong_examples": wrong_examples}
    dest = Path(args.out) if args.out else log_dir / "accuracy_report.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {dest}")


if __name__ == "__main__":
    main()
