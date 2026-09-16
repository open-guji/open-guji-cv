"""CLI 封装：`open_guji_cv.eval.llm_online_accuracy.compute_report` 的
命令行入口。核心聚合逻辑在包里（供控制台 `/api/llm_online_stats` 复用），
这里只管解析参数、打印、落报告文件。见 `eval/llm_online_accuracy.py` 模块头。

用法：
    PYTHONPATH=. python scripts/measure_llm_online_accuracy.py \\
        --log-dir output/llm_online_calls
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(REPO / "output" / "llm_online_calls"))
    ap.add_argument("--book", default=None, help="只看这本书；默认全部")
    ap.add_argument("--feedback-root", default=None,
                    help="反馈事件根目录；默认 EventLog 的 default_feedback_root()")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from open_guji_cv.eval.llm_online_accuracy import compute_report

    log_dir = Path(args.log_dir)
    if not log_dir.exists() or not any(log_dir.glob("*.jsonl")):
        print(f"没有线上调用日志（{log_dir}），还没在真实处理里开过 "
             "enable_online_llm，或者书名/路径不对")
        return

    feedback_root = Path(args.feedback_root) if args.feedback_root else None
    report = compute_report(log_dir, args.book, feedback_root)

    print(f"线上调用总数: {report['n_total_calls']}"
         f"（候选内命中: {report['n_answered_in_candidates']}）")
    print(f"已有人审最终判定可比对: {report['n_resolved']}（还没人审: "
         f"{report['n_answered_in_candidates'] - report['n_resolved']}"
         "——这些不计入正确率，不是错）")
    if report["n_resolved"]:
        print(f"线上正确率: {report['n_correct']}/{report['n_resolved']} = "
             f"{report['accuracy']:.2%}")
        print(f"\n{'provider/model':<24} {'n':>6} {'正确率':>8}")
        for key, d in sorted(report["by_model"].items()):
            print(f"{key:<24} {d['n']:>6} {d['accuracy']:>7.2%}")
    else:
        print("一条人审判定都还没对上——太早，先攒量")

    dest = Path(args.out) if args.out else log_dir / "accuracy_report.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {dest}")


if __name__ == "__main__":
    main()
