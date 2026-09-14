# -*- coding: utf-8 -*-
"""把字对复核事件（workspace feedback/touch_label_verdicts.jsonl）重放进 **workspace 裁决表**。

    python experiments/touch_resolve/replay_label_events.py [--apply]

为什么要有这一步（2026-09-14 实锤）：06 卡两轮字对复核的 40 处改字当时只写进了 open-guji-dataset，
没写 workspace 裁决表；而 `guji gold import` 是「workspace 打底、覆盖 dataset」——今天导入 drift 重标时
把 38 处改字**覆盖回了旧值**（vol03:7:9:3 其→豈 等）。裁决表才是导入的源头，改字必须落在这里。
规则：同一 (case, side) 后到覆盖；只有 opt 类裁决（选中了某个字）才改字；none / idk 不动。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import REPO  # noqa: F401  (保证从仓根跑)
from open_guji_cv.core.workspace import workspace_root
from open_guji_cv.feedback.consumers import verdict_store

SHARD = "char-segmentation/touching-cuts"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    fb = Path(workspace_root()) / "feedback" / "touch_label_verdicts.jsonl"
    events = [json.loads(l) for l in fb.read_text(encoding="utf-8").splitlines() if l.strip()]
    want: dict[tuple[str, str], str] = {}
    for e in events:                                   # 文件顺序 = 时间顺序，后到覆盖
        if e.get("chosen"):
            want[(e["case"], e["side"])] = e["chosen"]
    store = verdict_store()
    items = {i.id: i for i in store.list(SHARD)}
    changes, todo = [], []
    for (cid, side), ch in sorted(want.items()):
        it = items.get(cid)
        key = "char_above" if side == "above" else "char_below"
        if it is None:
            print("裁决表里没有", cid); continue
        cur = it.expected.get(key, "")
        if cur != ch:
            changes.append((cid, key, cur, "→", ch))
            it.expected[key] = ch
            todo.append(it)
    print(f"事件 {len(events)} 条，选字 {len(want)} 侧，裁决表需改 {len(changes)} 处")
    for c in changes: print("  ", *c)
    if not a.apply:
        print("（未写入；加 --apply 才改 workspace 裁决表；之后 `guji gold import char-segmentation/touching-cuts` 进数据集）")
        return 0
    added, updated = store.upsert(SHARD, todo, "字对复核（06 卡两轮）重放进裁决表：导入源头必须带上改字")
    print(f"upsert 新增 {added} 更新 {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
