"""把形近对消歧集导成**不含答案**的题面，供大模型（或人）盲测。

刻意不写出的东西：金标、金标来源、档位、以及字形层的候选覆盖率——
后者会把「形状怎么看」泄进来，而这一臂要单独量的正是**纯上下文**的
判别力。题号打乱（种子固定，可复现），免得同一形近对连着出、
答题时互相提示。
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20260826)
    args = ap.parse_args()

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = list(data["cases"])
    random.Random(args.seed).shuffle(cases)

    lines = ["# 形近对上下文消歧 · 盲测题面",
             "# △ 是待定字位。只凭上下文在两个选项里选一个。",
             "# 列内文本竖排从上往下；「前列」在其右、「后列」在其左。", ""]
    for i, c in enumerate(cases, 1):
        lines.append(f"[{i:03d}] {c['id']}  选项：{ '  '.join(c['options']) }")
        lines.append(f"      本列OCR : {c['col_masked']}")
        if c.get("col_ref_masked"):
            lines.append(f"      本列整理本: {c['col_ref_masked']}")
        if c.get("prev_ref") or c.get("prev_ocr"):
            lines.append(f"      前列     : {c.get('prev_ref') or c.get('prev_ocr')}")
        if c.get("next_ref") or c.get("next_ocr"):
            lines.append(f"      后列     : {c.get('next_ref') or c.get('next_ocr')}")
        lines.append("")
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")

    key = [{"n": i, "id": c["id"], "pair": c["pair"], "gold": c["gold"],
            "tier": c["tier"], "options": c["options"]}
           for i, c in enumerate(cases, 1)]
    kp = Path(args.out).with_suffix(".key.json")
    kp.write_text(json.dumps(key, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    print(f"题面 {args.out}（{len(cases)} 题）\n答案 {kp}（评分时才读）")


if __name__ == "__main__":
    main()
