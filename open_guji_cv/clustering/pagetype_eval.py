"""页型判别评测：主指标是**网格策略**判对没有。

为什么主指标不是八分类准确率
----------------------------
八分类里 body 占 75%，全判 body 就有 75% 准确率却毫无用处。真正决定管线
行为的是三选一的**网格策略**（skip / custom / standard），而且两个方向的
代价完全不对称：

- 该跳过却切了 → 产出一页垃圾（可被 bad_seg 等标记事后发现）；
- 该切却跳过了 → **整页真数据丢失**，下游连"这里有东西"都不知道。

所以除了策略准确率，单独报「漏切率」（把正文类判成 skip 的比例），它才是
不可接受的那一类错误。
"""

from __future__ import annotations

from collections import defaultdict

from .page_type import SKIP_TYPES, PageTypeLabel, policy_of


def evaluate(gold: list[PageTypeLabel],
             pred: dict[str, tuple[str, str]]) -> dict:
    """pred: {"book/page": (页型, 策略)}。"""
    scored = [g for g in gold if g.policy is not None]
    n_skipped = len(gold) - len(scored)

    per_type: dict[str, dict] = {}
    conf: dict[tuple[str, str], int] = defaultdict(int)
    n_ok = 0
    wrong_skip: list[str] = []      # 该切却跳过 —— 丢真数据
    wrong_keep: list[str] = []      # 该跳过却切了 —— 产出垃圾
    for g in scored:
        p = pred.get(g.key)
        if p is None:
            continue
        gp, pp = g.policy, p[1]
        conf[(gp, pp)] += 1
        d = per_type.setdefault(g.page_type, {"n": 0, "n_ok": 0})
        d["n"] += 1
        if gp == pp:
            n_ok += 1
            d["n_ok"] += 1
        elif pp == "skip":
            wrong_skip.append(g.key)
        elif gp == "skip":
            wrong_keep.append(g.key)
    n = sum(d["n"] for d in per_type.values())
    n_grid = sum(1 for g in scored if g.policy != "skip")
    n_skip_gold = sum(1 for g in scored if g.policy == "skip")
    for d in per_type.values():
        d["rate"] = round(d["n_ok"] / d["n"], 4) if d["n"] else 0.0
    return {
        "n_pages": n, "n_uncertain_skipped": n_skipped,
        "policy_accuracy": round(n_ok / n, 4) if n else 0.0,
        "lost_pages": len(wrong_skip),
        "lost_rate": round(len(wrong_skip) / n_grid, 4) if n_grid else 0.0,
        "junk_pages": len(wrong_keep),
        "skip_recall": round((n_skip_gold - len(wrong_keep)) / n_skip_gold, 4)
                       if n_skip_gold else 0.0,
        "n_skip_gold": n_skip_gold,
        "per_type": dict(sorted(per_type.items(),
                                key=lambda kv: -kv[1]["n"])),
        "wrong_skip": wrong_skip, "wrong_keep": wrong_keep,
    }


def format_report(report: dict) -> str:
    out = ["【逐页型】"]
    for t, v in report["per_type"].items():
        tag = "跳过" if t in SKIP_TYPES else "切分"
        out.append(f"  {t:<10}({tag}) n={v['n']:>4}  策略判对 {v['n_ok']:>4}"
                   f"  {v['rate']:>6.0%}")
    out += ["",
            f"网格策略准确率 {report['policy_accuracy']:.1%}"
            f"（{report['n_pages']} 页，另跳过 "
            f"{report['n_uncertain_skipped']} 页 uncertain）",
            f"该跳过的页检出率 {report['skip_recall']:.0%}"
            f"（金标 {report['n_skip_gold']} 页）",
            f"**误跳过正文页 {report['lost_pages']} 页**"
            f"（{report['lost_rate']:.2%}）—— 这是丢真数据，零容忍",
            f"该跳过却切了 {report['junk_pages']} 页 —— 产出垃圾，可事后标记"]
    if report["wrong_skip"]:
        out.append(f"  误跳过: {report['wrong_skip']}")
    if report["wrong_keep"]:
        out.append(f"  漏跳过: {report['wrong_keep']}")
    return "\n".join(out)
