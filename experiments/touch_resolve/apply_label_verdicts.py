# -*- coding: utf-8 -*-
"""把「粘连点金标字对复核」审查页的人裁结果收回并回写 touching-cuts 金标（显式导入这一步）。

    # 1) Artifact action:"read" 把线上页读回本地（大页会落成文件），然后：
    python experiments/touch_resolve/apply_label_verdicts.py read_back.html [--apply]

不带 --apply 只报：每张卡人裁 → 与金标一致 / 改成别的字 / 都不是 / 看不清；对照卡的一致率（人的基线）。
带 --apply：
  - 人裁结果先落 workspace：<workspace>/feedback/touch_label_verdicts.jsonl（追加，一行一卡，含候选顺序与原金标）；
  - 再改 open-guji-dataset/char-segmentation/touching-cuts/items.jsonl 里对应条目的 char_above/char_below，
    history 追加 {"change": "...", "ts", "why": "人裁 label review"}；「都不是」「看不清」不改金标，只记事件。
边界：改数据集金标是显式动作（本脚本 --apply），生产管线不读这里的任何东西。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from common import REPO
from open_guji_cv.core.workspace import workspace_root

DATASET = REPO.parent / "open-guji-dataset"
ITEMS = DATASET / "char-segmentation" / "touching-cuts" / "items.jsonl"
PAT = re.compile(r'<script[^>]*id="data"[^>]*>(.*?)</script>', re.S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    html = Path(a.html).read_text(encoding="utf-8")
    m = PAT.search(html)
    if not m:
        sys.exit("这页里没有 #data")
    d = json.loads(m.group(1).replace("<\\/", "</"))
    payload = d.get("payload", d)
    rows = {r["id"]: r for r in payload["rows"]}
    verdicts = d.get("verdicts", {})
    print(f"卡 {len(rows)}，已裁 {len(verdicts)}")

    items = [json.loads(l) for l in ITEMS.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_id = {it["id"]: it for it in items}
    stats = Counter(); changes = []; events = []
    for cid, vt in verdicts.items():
        r = rows.get(cid)
        if not r:
            continue
        v = vt["v"]; side = r["side"]; gold_key = "char_above" if side == "above" else "char_below"
        it = by_id.get(r["case"]); gold = (it or {}).get("expected", {}).get(gold_key, "")
        chosen = r["opts"][int(v[3:])] if v.startswith("opt") else None
        if chosen is None:
            kind = v                                # none / idk
        elif chosen == gold:
            kind = "same"
        else:
            kind = "changed"
        stats[(r["stratum"], kind)] += 1
        events.append({"id": cid, "case": r["case"], "side": side, "stratum": r["stratum"], "opts": r["opts"],
                       "verdict": v, "chosen": chosen, "gold_before": gold, "t": vt.get("t"),
                       "source": "artifact:touch-label-review-2026-09-13-v1"})
        if kind == "changed":
            changes.append((it, gold_key, gold, chosen, cid))
    for (stratum, kind), n in sorted(stats.items()):
        print(f"  {stratum:8s} {kind:8s} {n}")
    ctrl = [e for e in events if e["stratum"] == "control" and e["chosen"]]
    if ctrl:
        print(f"对照卡一致率 {sum(e['chosen']==e['gold_before'] for e in ctrl)}/{len(ctrl)}")
    print(f"将改金标 {len(changes)} 处：", [(c[4], c[2], '→', c[3]) for c in changes][:40])
    if not a.apply:
        print("（未写入；加 --apply 才落 workspace 事件并改金标）")
        return 0
    ws = workspace_root() or REPO
    fb = ws / "feedback" / "touch_label_verdicts.jsonl"; fb.parent.mkdir(parents=True, exist_ok=True)
    with fb.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for it, key, old, new, cid in changes:
        it["expected"][key] = new
        it.setdefault("history", []).append({"change": f"{key} {old} → {new}", "ts": ts, "why": f"人裁 label review（{cid}）"})
    ITEMS.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
    print(f"已写 {fb}（{len(events)} 条事件），改金标 {len(changes)} 处 → {ITEMS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
