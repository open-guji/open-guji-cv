"""跑 llm_context 评测集：真调用（有 key）或 --mock（没 key 也能跑通全链路）。

    # key 一到，两版 prompt、两家 provider 各跑一遍：
    export GLM_API_KEY=...        # 或 DASHSCOPE_API_KEY
    PYTHONPATH=. python scripts/eval_llm_context.py output/llm_context_evalset/evalset.json \\
        --provider glm --prompt-version candidates \\
        --cache output/llm_context_evalset/cache_glm_candidates.json \\
        --out output/llm_context_evalset/report_glm_candidates.json

    # 没 key 时验证链路（parse/打分/报表都真的跑，只是回答是造的）：
    PYTHONPATH=. python scripts/eval_llm_context.py output/llm_context_evalset/evalset.json \\
        --provider mock --prompt-version direct --out /tmp/mock_report.json

因为本评测集的题全是「现有 gated_ngram 判错」的槽位，`current_strategy`
在这个集上的准确率**按构造就是 0**——这不是 bug，是选题规则决定的
（任务书 §二·1）。这里报的数字要看的是外部 LLM 在这批「ngram 认输」的
槽位上能救回多少，不是跟 ngram 比全量。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.llm_context import (  # noqa: E402
    LLMContextJudge, MockJudge, NoAPIKeyError, prompt_direct,
    prompt_with_candidates)


def build_prompt(item: dict, book_title: str, version: str, with_reason: bool) -> str:
    if version == "direct":
        return prompt_direct(item, book_title)
    if version == "candidates":
        return prompt_with_candidates(item, book_title, with_reason=with_reason)
    raise ValueError(f"未知 prompt 版本: {version!r}（可用: direct, candidates）")


def default_mock_responder(items_by_id: dict, mode: str):
    """--provider mock 时的造答函数：baseline 复述基线（验证「答案在候选内、
    但是错的」这条链路）；gold 直接抄金标（验证「能救回」这条链路整个能打分对）。
    话痨包一层句子测试解析退化分支。"""

    def _respond(item_id: str, prompt: str) -> str:
        it = items_by_id[item_id]
        if mode == "gold":
            char = it["gold"]
        else:
            char = it["current_strategy"]["baseline_top1"]
        return f"根据上下文，我认为这里应该是「{char}」字。"

    return _respond


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("evalset")
    ap.add_argument("--provider", required=True, choices=["glm", "qwen", "mock"])
    ap.add_argument("--prompt-version", required=True,
                    choices=["direct", "candidates"])
    ap.add_argument("--with-reason", action="store_true",
                    help="candidates 版让模型附一句理由（只进日志，不参与判分）")
    ap.add_argument("--model", default=None, help="覆盖 provider 默认模型名")
    ap.add_argument("--mock-mode", default="baseline", choices=["baseline", "gold"],
                    help="--provider mock 时的造答策略，见脚本头")
    ap.add_argument("--cache", default=None, help="真调用的缓存文件路径")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 题，调试用")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.evalset).read_text(encoding="utf-8"))
    items = data["items"]
    if args.limit:
        items = items[: args.limit]
    titles = data["meta"].get("book_titles", {})

    if args.provider == "mock":
        items_by_id = {it["id"]: it for it in items}
        judge = MockJudge(responder=default_mock_responder(items_by_id, args.mock_mode))
    else:
        try:
            judge = LLMContextJudge(args.provider, model=args.model,
                                    cache_path=args.cache)
        except NoAPIKeyError as e:
            report = {"provider": args.provider, "skipped": True, "reason": str(e)}
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"跳过 provider={args.provider}：{e}")
            return

    rows = []
    n_correct = n_parse_fail = n_current_strategy_correct = 0
    t0 = time.time()
    for it in items:
        book_title = titles.get(it.get("source_item"), it.get("source_item", ""))
        prompt = build_prompt(it, book_title, args.prompt_version, args.with_reason)
        ans = judge.ask(it["id"], prompt)
        correct = ans.parsed_char == it["gold"]
        n_correct += correct
        n_parse_fail += not ans.parse_ok
        n_current_strategy_correct += it["current_strategy"]["final_decision"] == it["gold"]
        rows.append({
            "id": it["id"], "gold": it["gold"],
            "candidates_chars": it["candidates_chars"],
            "current_strategy_final": it["current_strategy"]["final_decision"],
            "llm_raw_text": ans.raw_text, "llm_parsed_char": ans.parsed_char,
            "llm_parse_ok": ans.parse_ok, "llm_correct": correct,
            "llm_answer_in_candidates": ans.parsed_char in it["candidates_chars"]
                                       if ans.parsed_char else False,
            "cached": ans.cached, "latency_s": round(ans.latency_s, 3),
            "error": ans.error,
        })

    n = len(items)
    report = {
        "provider": args.provider, "model": getattr(judge, "model", None),
        "prompt_version": args.prompt_version, "with_reason": args.with_reason,
        "evalset": str(Path(args.evalset).as_posix()),
        "n": n,
        "llm_accuracy": round(n_correct / n, 4) if n else 0.0,
        "llm_parse_fail_rate": round(n_parse_fail / n, 4) if n else 0.0,
        "current_strategy_accuracy_on_this_set":
            round(n_current_strategy_correct / n, 4) if n else 0.0,
        "wall_time_s": round(time.time() - t0, 2),
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"provider={args.provider} prompt={args.prompt_version} "
         f"n={n} llm_accuracy={report['llm_accuracy']:.2%} "
         f"parse_fail_rate={report['llm_parse_fail_rate']:.2%} "
         f"（现有策略在这个集上按构造应为 0：{report['current_strategy_accuracy_on_this_set']:.2%}）")
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
