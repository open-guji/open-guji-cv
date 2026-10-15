#!/usr/bin/env python3
"""保真对照（开发用，窗口不跑）：用终头 1deec56 的**真实**函数算缓存键，再让 find_stale_bindings_cache.py 判——它复刻的键必须与真实代码一致。
用法：python3 selftest_find_stale_real_keys.py <终头 cv 检出目录>   （无 cv2 时用桩；只在 /tmp 合成目录里写，不碰任何真数据）
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
from unittest import mock

CV = sys.argv[1]
sys.modules["cv2"] = mock.MagicMock()
sys.path.insert(0, CV)
T = Path(tempfile.mkdtemp(prefix="fidel208kx."))
WS = T / "ws"
os.environ["GUJI_WORKSPACE"] = str(WS)
os.environ.pop("GUJI_PRODUCTS_DIR", None)
from open_guji_cv.feedback import bindings as B                      # noqa: E402
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event   # noqa: E402
from open_guji_cv.products.store import ProductStore                 # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "find_stale_bindings_cache.py"
book = "vol09"
(WS / "feedback" / "events").mkdir(parents=True)
for pg in (1, 2, 3):
    d = WS / "products" / book / "row_segment"; d.mkdir(parents=True, exist_ok=True)
    (d / f"p{pg:04d}.json").write_text(json.dumps({"page": pg, "x": pg * 7}), encoding="utf-8")
log = EventLog(WS / "feedback")
evs = []
evs.append(make_event("b-confirm", 1, "confirm", EventTarget(step="seed_admit", unit="cell", key=f"{book}:1:3:5", book=book, page=1), {"shape": "甲"}))
evs.append(make_event("b-confirm", 2, "confirm", EventTarget(step="seed_admit", unit="cell", key=f"{book}:1:4:2a", book=book, page=1), {"shape": "乙"}))
evs.append(make_event("b-confirm", 3, "confirm", EventTarget(step="seed_admit", unit="cell", key=f"{book}:2:1:1", book=book, page=2), {"shape": "丙"}))
evs.append(make_event("b-vision", 1, "confirm", EventTarget(step="seed_admit", unit="cell", key=f"{book}:3:1:1", book=book, page=3), {"shape": "丁", "source": "vision"}))   # 看图结论：不算
evs.append(make_event("b-ret", 1, "cutline", EventTarget(step="column_warp", unit="column", key=f"{book}:3:2", book=book, page=3), {}))
log.append(evs)
(WS / "feedback" / "anchors").mkdir(parents=True)
bf = {evs[0].id: {"space": "page", "bbox": [1, 2, 3, 4]}}
(WS / "feedback" / "anchors" / f"{book}.jsonl").write_text(json.dumps({"event": evs[0].id, "anchor": bf[evs[0].id]}, ensure_ascii=False) + "\n", encoding="utf-8")

# —— 用真实函数写出「真实代码会认账」的缓存 ——
store = ProductStore(WS / "products")
by_page, by_ret, backfill = B._verdict_events(book, EventLog(WS / "feedback")), B._return_trigger_events(book, EventLog(WS / "feedback")), None
from open_guji_cv.feedback.anchor_backfill import load_backfill  # noqa: E402
backfill = load_backfill(book)
cdir = WS / "feedback" / "bindings" / book; cdir.mkdir(parents=True)
for pg in sorted(set(by_page) | set(by_ret)):
    sig = B._sig(by_page.get(pg, []), by_ret.get(pg), backfill)
    (cdir / f"p{pg:04d}.json").write_text(json.dumps({"v": B._VERSION, "cells_sha": store.sha(book, "row_segment", f"p{pg:04d}"), "sig": sig, "rows": []}), encoding="utf-8")

def run():
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(WS), book], capture_output=True, text=True)
    return r.returncode, r.stdout

rc, out = run(); print("【真实键写的缓存，脚本应判 全部一致 rc=0】rc=", rc); print(out)
assert rc == 0, "复刻的缓存键与真实代码不一致！"
# 改产物 → cells_sha 陈旧
(WS / "products" / book / "row_segment" / "p0002.json").write_text(json.dumps({"page": 2, "x": 999}), encoding="utf-8")
rc, out = run(); print("【改 p0002 产物，应 rc=1 且只指 p0002 的 cells_sha】rc=", rc); print(out); assert rc == 1 and "p0002" in out and "cells_sha" in out and "p0001" not in out.split("== ")[1].split("（一致")[0]
# 补一条新裁决事件 → sig 陈旧
log.append([make_event("b-confirm", 4, "confirm", EventTarget(step="seed_admit", unit="cell", key=f"{book}:1:9:9", book=book, page=1), {"shape": "戊"})])
rc, out = run(); print("【p0001 多一条裁决事件，应 rc=1 且 p0001 sig 不一致】rc=", rc); print(out); assert rc == 1 and "p0001" in out and "sig" in out
print("保真对照通过：脚本复刻的 cells_sha／sig 与终头真实函数一致。")
