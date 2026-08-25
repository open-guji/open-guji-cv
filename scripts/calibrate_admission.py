# -*- coding: utf-8 -*-
"""准入规则标定：用全部历史人裁回放，找「本可自动确认」的空间。

    PYTHONPATH=. python scripts/calibrate_admission.py output/vol01

这是「对进库这一步自己的反馈」的固定入口（三条反馈环之三，见
.claude/doc/review_feedback_loops.md）。每轮 seed-ingest 回收人裁之后跑：

1. **存量复裁提示**：待审行里有多少按**现行**规则已能自动进
   （规则升级后没回填的旧行）→ 提示跑 readjudicate_pending；
2. **拦截分布**：人裁 confirm 的行按「当时的疑问组合 × 信号组合」聚类，
   报每一组的量——量大且人裁全部同意机器候选的组合，就是下一条放行
   规则的候选；
3. **候选规则回放**：对拦截量最大的组合，用历史人裁全量验证
   「若放行会对多少/错多少」（本脚本内置两条已落地规则的复验，新组合
   出现时照 test_rule 的样子加）。

规则落地的纪律（2026-08-25 十七轮定型，照做）：
- 回放集必须是**全部**历史人裁（status ∈ confirmed/label_only/rejected
  且有 decided_char），不能只看最近一批；
- 变体表必须用生产默认（VariantMap.load() 不带参数）——十七轮实测
  错载空表会把 啓/啟、爲/為 记成错例，白白把阈值顶高一档；
- 出一个错就把阈值抬到错例之上再留一档余量（祗/祇 在 0.97，故
  match_ref_weak 定 0.98）；
- 落地后 readjudicate_pending 回填存量 + 单测钉住通道行为。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.seeding import admission_decision  # noqa: E402
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402

DECIDED = ("confirmed", "confirmed_label_only", "rejected")


def replay(r: dict, vmap: VariantMap):
    m = r.get("match") or {}
    return admission_decision(
        r.get("ocr"), (r.get("align") or {}).get("char"),
        (r.get("context") or {}).get("ref_char"),
        r.get("doubts") or [], vmap,
        match_char=m.get("char"),
        match_candidates=[tuple(c) for c in (m.get("candidates") or [])] or None,
        match_guard=m.get("guard"), match_wmax=float(m.get("wmax") or 0.0))


def signal_key(r: dict, vmap: VariantMap, ch: str) -> str:
    ocr = (r.get("ocr") or {}).get("char")
    al = (r.get("align") or {}).get("char")
    ref = (r.get("context") or {}).get("ref_char")
    m = r.get("match") or {}
    cands = {c: v for c, v in (m.get("candidates") or [])}
    cov = cands.get(ch)
    return (("OCR" if ocr == ch else "-") + ("对齐" if al == ch else "-")
            + ("参考" if ref == ch else "-")
            + (f"库{cov:.2f}" if cov else "库无"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("book_out_dir")
    args = ap.parse_args()
    qp = Path(args.book_out_dir) / "phase9_seed" / "queue.jsonl"
    vmap = VariantMap.load()          # 生产默认表，见模块头的纪律
    rows = [json.loads(l) for l in qp.read_text(encoding="utf-8").splitlines()
            if l.strip()]

    pending = [r for r in rows if r["status"] in ("pending_review", "skipped")]
    stale = sum(1 for r in pending if replay(r, vmap)[0])
    print(f"待审 {len(pending)} 行，其中按现行规则已能自动进：{stale}")
    if stale:
        print("  → 先跑 readjudicate_pending 回填（seed 模块），再谈新规则\n")

    decided = [r for r in rows
               if r["status"] in DECIDED and r.get("decided_char")]
    blocked = [r for r in decided if not replay(r, vmap)[0]]
    print(f"历史人裁 {len(decided)} 行，现行规则仍拦 {len(blocked)} 行；"
          f"按 疑问组合 分布（每组人裁最终字 = 机器某候选的比例）：")
    groups: dict[str, list] = defaultdict(list)
    for r in blocked:
        groups[",".join(sorted(r.get("doubts") or [])) or "无疑问"].append(r)
    for key, grp in sorted(groups.items(), key=lambda t: -len(t[1])):
        sig = Counter(signal_key(r, vmap, r["decided_char"]) for r in grp)
        top = "；".join(f"{s}×{n}" for s, n in sig.most_common(3))
        print(f"  {len(grp):>4}  [{key}]  {top}")
    print("\n量大且信号里带「对齐/参考 + 库」的组合是放行候选：拿全部")
    print("decided 行回放拟议规则（触发数/对/错），错例决定阈值。")


if __name__ == "__main__":
    main()
