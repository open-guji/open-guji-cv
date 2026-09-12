"""一条命令：出题 → 调外部大模型 API → 算分 → 出报告。

用户 2026-09-10 改令（任务书 §二「⛔ 交付一个完整程序，不要分段」）：
不要「出题 jsonl 交给别人跑再回填」，本脚本内部把建评测集
（同 `build_llm_context_evalset.py` 的逻辑）与调用/解析/打分
（同 `eval_llm_context.py` 的逻辑）接成一条命令：

    export GLM_API_KEY=...   # 或什么都不设——会自动去 overview 仓
                              # .secret/api-keys.cfg 找（见任务书）
    PYTHONPATH=. .venv/bin/python scripts/run_llm_context_eval.py \\
        --book vol01 --pages dev_set --n 100 --provider qwen

    # 换个更便宜的档对照（任务书点名 glm-4-flash 答错过，值得单独跑一份）：
    PYTHONPATH=. .venv/bin/python scripts/run_llm_context_eval.py \\
        --book vol01 --n 100 --provider glm --model glm-4-flash

跑完一份 md + json 报告到 `output/llm_context_evalset/`，**不接生产**——
只读 `context-correction` 金标与 `open-guji-cv` 语料，不碰
`context_decide.py` / `context_step.py`，不写库。

## `--pages` 的真实语义（别被参数名字骗了）

`context-correction`（本脚本唯一的候选+金标来源）只覆盖 vol01 p4–p14，
`books/vol01.yaml` 的 `dev_set` 是另外 11 页——两边交集只有 p11 的 29 个
槽位（`Step6-上下文裁决/README.md` 记录过的已知缺口）。所以
`--pages dev_set`（跟其它子命令保持同名同形）在这里**不会**把题面收窄
到那 11 页——那样只剩 29 个槽位，凑不够 `--n`。默认用
`context-correction` 的全部页；给显式页号列表（如 `--pages 13,14`）才会
真的筛。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import build_llm_context_evalset as bld  # noqa: E402
from open_guji_cv.clustering.llm_context import (  # noqa: E402
    LLMContextJudge, MockJudge, NoAPIKeyError, prompt_direct,
    prompt_with_candidates, redact_key)
from open_guji_cv.core.workspace import corpus_path  # noqa: E402


def build_prompt(item: dict, book_title: str, version: str, with_reason: bool) -> str:
    if version == "direct":
        return prompt_direct(item, book_title)
    if version == "candidates":
        return prompt_with_candidates(item, book_title, with_reason=with_reason)
    raise ValueError(f"未知 prompt 版本: {version!r}（可用: direct, candidates）")


def filter_by_pages(samples: list[dict], pages_arg: str) -> tuple[list[dict], str]:
    """`--pages` 的真实处理：dev_set/all → 不筛（见脚本头）；显式页号列表 → 真筛。"""
    if pages_arg in ("dev_set", "all", None):
        note = ("dev_set" if pages_arg == "dev_set" else "all")
        if pages_arg == "dev_set":
            print("⚠ --pages dev_set：context-correction 与 vol01 dev_set 只有 "
                 "p11 有交集（29 槽位），凑不够题——本脚本用全部 context-correction "
                 "页，不按 dev_set 筛（见脚本头注释）。")
        return samples, note
    wanted = {p.strip() for p in pages_arg.split(",") if p.strip()}
    out = [s for s in samples if str(s.get("page")) in wanted]
    return out, pages_arg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", default="vol01", help="书 id（取 BookSpec.title 填 prompt）")
    ap.add_argument("--pages", default="dev_set",
                    help="dev_set/all（默认，不筛）或显式页号列表如 13,14；见脚本头")
    ap.add_argument("--dataset", default=str(REPO.parent / "open-guji-dataset" / "context-correction"))
    ap.add_argument("--general-corpus",
                    default=str(REPO / "corpus" / "external" / "daizhige_zhaoling.txt"))
    ap.add_argument("--book-corpus",
                    default=str(corpus_path("zongmu_wuyingdian_reference.txt")))
    ap.add_argument("--book-weight", type=float, default=bld.DEFAULT_BOOK_WEIGHT)
    ap.add_argument("--gate", type=float, default=bld.DEFAULT_MARGIN_GATE)
    ap.add_argument("--context-window", type=int, default=bld.DEFAULT_CONTEXT_WINDOW)
    ap.add_argument("--window-chars", type=int, default=bld.DEFAULT_WINDOW_CHARS)
    ap.add_argument("-n", "--n", type=int, default=100, dest="n",
                    help="评测题数上限（够用就行，任务书 §二·1）")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--provider", required=True, choices=["glm", "qwen", "mock"])
    ap.add_argument("--model", default=None, help="覆盖 provider 默认模型名，"
                    "比如 --provider glm --model glm-4-flash 对照便宜档")
    ap.add_argument("--prompt-version", default="candidates",
                    choices=["direct", "candidates"])
    ap.add_argument("--with-reason", action="store_true")
    ap.add_argument("--mock-mode", default="baseline", choices=["baseline", "gold"])
    ap.add_argument("--rate-limit-s", type=float, default=0.3,
                    help="每次真请求后的固定延迟，别把整批打爆")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--out-dir", default=str(REPO / "output" / "llm_context_evalset"))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 出题：与 build_llm_context_evalset.py 同一套函数，不重复造轮子 ──
    root = Path(args.dataset)
    samples = bld.load_samples(root)
    if not samples:
        print(f"没有可用样本：{root}")
        raise SystemExit(1)
    samples, pages_note = filter_by_pages(samples, args.pages)
    if not samples:
        print(f"--pages {args.pages!r} 筛完一条样本都不剩，检查页号是否在 "
             f"{root} 的覆盖范围内")
        raise SystemExit(1)

    gold_texts = ["".join(sl["gold"] for c in s["columns"] for sl in c["slots"])
                 for s in samples]
    lm, provenance = bld.build_lm(args.general_corpus, args.book_corpus,
                                  args.book_weight, gold_texts)

    from open_guji_cv.clustering.context_step import build_strategy
    from open_guji_cv.clustering.variants import VariantMap
    vpath = REPO / "config" / "charset" / "variants.tsv"
    vm = VariantMap.load(vpath if vpath.exists() else None)
    decider = build_strategy("gated_ngram", lm=lm, semantic_fn=vm.semantic)

    items, stats = bld.build_items(samples, decider, args.gate,
                                   args.context_window, args.window_chars)
    print(f"出题：{stats}")
    selected = bld.stratified_sample(items, args.n, args.seed)
    selected.sort(key=lambda it: it["id"])
    if not selected:
        print("挑不出题——现有策略在筛出来的页上一条都没判错？检查 --pages/--dataset。")
        raise SystemExit(1)

    book_title = bld.book_title(args.book)
    print(f"出题完成：{len(selected)} 题（书名：{book_title}，页选择：{pages_note}）")

    # ── 调用：真 provider 缺 key 直接报错退出；mock 只用于联调/回归 ──
    cache_path = out_dir / f"cache_{args.provider}_{args.model or 'default'}.json"
    if args.provider == "mock":
        items_by_id = {it["id"]: it for it in selected}

        def _mock_respond(item_id: str, prompt: str) -> str:
            it = items_by_id[item_id]
            char = (it["gold"] if args.mock_mode == "gold"
                   else it["current_strategy"]["baseline_top1"])
            return f"「{char}」"

        judge = MockJudge(responder=_mock_respond)
        print("provider=mock：只验证链路，不代表真实模型准确率")
    else:
        try:
            judge = LLMContextJudge(args.provider, model=args.model,
                                    cache_path=cache_path, timeout=args.timeout,
                                    max_retries=args.max_retries,
                                    rate_limit_s=args.rate_limit_s)
        except NoAPIKeyError as e:
            print(f"缺 key，报错退出：{e}")
            raise SystemExit(1)
        print(f"provider={args.provider} model={judge.model} "
             f"key 来源={judge.key_source}（{redact_key(judge._api_key)}）")

    # ── 打分 ──────────────────────────────────────────────────────────
    rows = []
    n_correct = n_parse_fail = n_current_strategy_correct = 0
    total_ptoks = total_ctoks = 0
    t0 = time.time()
    for i, it in enumerate(selected, 1):
        prompt = build_prompt(it, book_title, args.prompt_version, args.with_reason)
        ans = judge.ask(it["id"], prompt)
        correct = ans.parsed_char == it["gold"]
        n_correct += correct
        n_parse_fail += not ans.parse_ok
        n_current_strategy_correct += it["current_strategy"]["final_decision"] == it["gold"]
        total_ptoks += ans.prompt_tokens
        total_ctoks += ans.completion_tokens
        rows.append({
            "id": it["id"], "gold": it["gold"],
            "candidates_chars": it["candidates_chars"],
            "current_strategy_final": it["current_strategy"]["final_decision"],
            "llm_raw_text": ans.raw_text, "llm_parsed_char": ans.parsed_char,
            "llm_parse_ok": ans.parse_ok, "llm_correct": correct,
            "llm_answer_in_candidates": (ans.parsed_char in it["candidates_chars"]
                                         if ans.parsed_char else False),
            "cached": ans.cached, "latency_s": round(ans.latency_s, 3),
            "prompt_tokens": ans.prompt_tokens,
            "completion_tokens": ans.completion_tokens,
            "error": ans.error,
        })
        if i % 25 == 0 or i == len(selected):
            print(f"  {i}/{len(selected)} …")

    n = len(selected)
    report = {
        "provider": args.provider, "model": getattr(judge, "model", None),
        "prompt_version": args.prompt_version, "with_reason": args.with_reason,
        "book": args.book, "book_title": book_title, "pages": pages_note,
        "n": n,
        "llm_accuracy": round(n_correct / n, 4) if n else 0.0,
        "llm_parse_fail_rate": round(n_parse_fail / n, 4) if n else 0.0,
        "current_strategy_accuracy_on_this_set":
            round(n_current_strategy_correct / n, 4) if n else 0.0,
        "note_current_strategy_accuracy": (
            "这个数按构造应为 0：题都是「现有策略判错」的槽位，见任务书 §二·1"),
        "token_usage": {"prompt_tokens": total_ptoks, "completion_tokens": total_ctoks,
                        "total_tokens": total_ptoks + total_ctoks,
                        "note": "官方单价会变，本报告只给用量，不猜成本；"
                                "换算成本请查 open.bigmodel.cn / dashscope 当前定价"},
        "wall_time_s": round(time.time() - t0, 2),
        "source_stats": stats,
        "rows": rows,
    }
    stem = f"report_{args.provider}_{report['model']}_{args.prompt_version}"
    stem = stem.replace("/", "_")
    out_json = out_dir / f"{stem}.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    out_md = out_dir / f"{stem}.md"
    out_md.write_text(
        f"# {args.provider}/{report['model']}（{args.prompt_version}"
        f"{'+理由' if args.with_reason else ''}）在 {n} 题上的成绩单\n\n"
        f"- 书：{book_title}\n"
        f"- 题目来源：{args.dataset}，页选择 {pages_note}\n"
        f"- **LLM 准确率：{report['llm_accuracy']:.2%}**"
        f"（解析失败率 {report['llm_parse_fail_rate']:.2%}）\n"
        f"- 现有策略在这批题上的准确率：{report['current_strategy_accuracy_on_this_set']:.2%}"
        f"（按构造应为 0，非 0 说明选题脚本有 bug，务必核查）\n"
        f"- token 用量：prompt {total_ptoks} + completion {total_ctoks} "
        f"= {total_ptoks + total_ctoks}\n"
        f"- 耗时：{report['wall_time_s']}s\n",
        encoding="utf-8")

    print(f"\nprovider={args.provider} model={report['model']} "
         f"prompt={args.prompt_version} n={n} "
         f"llm_accuracy={report['llm_accuracy']:.2%} "
         f"parse_fail_rate={report['llm_parse_fail_rate']:.2%} "
         f"tokens={total_ptoks}+{total_ctoks}")
    print(f"→ {out_json}\n→ {out_md}")


if __name__ == "__main__":
    main()
