# -*- coding: utf-8 -*-
"""把快审表（`char_review_sheet.py --grid`）导出的结果写成人审 confirm 事件并落库（GUJI-750）。

输入 JSON：`{"book","ok":[[格号,字],…],"bad":[格号,…]}`。`ok` 里每格一条
`confirm(v="confirm", shape=字)` 事件（actor=user、source=char_review，是人亲审），
再跑 `glyphdb_admit` 消费者把字块写进本工作区的字形库。`bad` 不写事件，只在报告里列出。

用法：GUJI_WORKSPACE=<工作区> ingest_char_review.py <result.json> [--batch NAME] [--dry-run]
只写本机 feedback/events 和 glyph.db，不推中心库（推库走 `guji db push`，要另行同意）。"""
import argparse
import json
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument("result")
ap.add_argument("--batch", default="char-review-grid")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
res = json.load(open(a.result, encoding="utf-8"))
if not os.environ.get("GUJI_WORKSPACE"):
    sys.exit("先设 GUJI_WORKSPACE")

from open_guji_cv.feedback.consumers import route_and_consume
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

book = res["book"]
bad = set(res.get("bad", []))
log = EventLog()
base = log.latest_seq(a.batch) + 1
evs = []
for k, (cid, ch) in enumerate((x for x in res["ok"] if x[0] not in bad)):
    _b, page, col, slot = cid.split(":")
    import re
    m = re.fullmatch(r"(-?\d+)([ab]?)", slot)
    evs.append(make_event(a.batch, base + k, "confirm",
                          EventTarget(step="seed_admit", unit="cell", key=cid, book=book,
                                      page=int(page), col=int(col), slot=int(m.group(1))),
                          {"v": "confirm", "shape": ch, "source": "char_review"}))
print(f"确认 {len(evs)} 格，剔除 {len(bad & {x[0] for x in res['ok']})} 格，不对 {len(bad)} 格")
if a.dry_run:
    out = route_and_consume(log, batch=a.batch, dry_run=True) if log.read(a.batch) else {}
    print("dry-run：不写事件、不落库")
    sys.exit(0)
log.append(evs)
print(json.dumps(route_and_consume(log, batch=a.batch), ensure_ascii=False)[:1500])
