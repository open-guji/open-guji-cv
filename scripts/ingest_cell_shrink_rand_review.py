# -*- coding: utf-8 -*-
"""把 Step4 随机层裁决台的裁决收回事件日志、消费进 `char-segmentation/instances`。

    PYTHONPATH=. python scripts/ingest_cell_shrink_rand_review.py \
        --html artifacts/cell_shrink_rand_review.html --batch cell_shrink_rand_r1

裁决页导出的是 `{id: {v, t}}`（`v` = clean/truncated/contaminated/not_text），
落库要的是 `kind="confirm", payload.v="seg_defect", payload.quality=<verdict>`
（`consumers.py::_expected_of` 认这个形状），所以不能直接走
`harvest.from_page_html` 的默认 kind——这里显式包一层。

`stratum="rand_human"`：与既有的 `self_assess_r1~r4`（`label_origin=model`，
算法自评）和其余定向层分开，报数时不能合并算。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.feedback.consumers import route_and_consume  # noqa: E402
from open_guji_cv.feedback.events import Event, EventLog, EventTarget, make_event  # noqa: E402
from open_guji_cv.feedback.harvest import parse_card_id  # noqa: E402

_DATA_RE = re.compile(r'<script[^>]*id="data"[^>]*>(.*?)</script>', re.S)


def load_verdicts(html_path: Path) -> dict[str, dict]:
    text = html_path.read_text(encoding="utf-8")
    m = _DATA_RE.search(text)
    if not m:
        raise ValueError("页面里没有 #data —— 确认读的是 Artifact 导出的裁决页本身")
    data = json.loads(m.group(1).replace("<\\/", "</"))
    return data.get("verdicts") or {}


def to_events(verdicts: dict[str, dict], batch: str, stratum: str) -> list[Event]:
    rows = [(cid, v) for cid, v in verdicts.items() if isinstance(v, dict) and v.get("v")]
    rows.sort(key=lambda kv: (kv[1].get("t") or 0, kv[0]))
    out = []
    for i, (cid, v) in enumerate(rows, 1):
        target = EventTarget(step="cell_shrink", unit="cell", key=cid, **parse_card_id(cid))
        payload = {"v": "seg_defect", "quality": v["v"], "stratum": stratum}
        out.append(make_event(batch, i, "confirm", target, payload, ts=None))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--stratum", default="rand_human")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    verdicts = load_verdicts(Path(a.html))
    print(f"页面里 {len(verdicts)} 条裁决")
    events = to_events(verdicts, a.batch, a.stratum)
    print(f"→ {len(events)} 条 confirm/seg_defect 事件")

    log = EventLog()
    if a.dry_run:
        from collections import Counter
        print("dry-run，不写事件日志。quality 分布：",
              dict(Counter(e.payload["quality"] for e in events)))
        return

    n = log.append(events)
    print(f"写入事件日志 {n} 条新事件（{a.batch}）")
    result = route_and_consume(log, batch=a.batch)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
