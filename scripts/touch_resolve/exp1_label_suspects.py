# -*- coding: utf-8 -*-
"""从实验一产出里导出「金标字对可疑」清单：gold 切法下识别 fused@5 都没命中真字、且 cls top-1 置信 ≥0.5 的侧。
这些多半是整理本对齐错位或整理本与刻本用字不同，该交人裁后回写 touching-cuts 的 char_above/char_below。

    python scripts/touch_resolve/exp1_label_suspects.py   → out/exp1/label_suspects.json
"""
from __future__ import annotations
import json
from common import OUT_ROOT, jdump

per = json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))
rows = []
for r in per:
    for side, truth in (("above", r["char_above"]), ("below", r["char_below"])):
        rk = r["rank"]["gold"][f"fused_{side}"]
        tk = (r["topk"]["gold"].get(side) or {})
        cls = tk.get("cls") or []
        if (rk is None or rk > 5) and cls and cls[0][1] >= 0.5:
            rows.append({"id": r["id"], "verdict": r["verdict"], "side": side, "gold_char": truth,
                         "pred": cls[0][0], "pred_conf": round(cls[0][1], 3),
                         "top3": list((tk.get("fused") or [])[:3])})
rows.sort(key=lambda x: -x["pred_conf"])
jdump(rows, OUT_ROOT / "exp1" / "label_suspects.json")
print(f"可疑字对标签 {len(rows)} 侧（置信 ≥0.5 且真字不在 fused@5）")
for x in rows[:40]:
    print(f"  {x['id']:18s} {x['verdict']:8s} {x['side']:5s} 金标 {x['gold_char']} → 识别 {x['pred']} ({x['pred_conf']:.2f})  top3 {''.join(x['top3'])}")
