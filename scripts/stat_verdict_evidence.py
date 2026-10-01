# -*- coding: utf-8 -*-
"""只读统计：各书现有人裁事件里带 anchor / bbox / 图像指纹 / 产物版本的比例。

不写任何东西。用法：
    GUJI_WORKSPACE=/path/to/guji-workspace/<ws> python scripts/stat_verdict_evidence.py
    python scripts/stat_verdict_evidence.py --events-dir <ws>/feedback/events [--json]
按 `target.book`（缺失则取 key 的第一段）分组；只数会进绑定/评测的裁决类
（confirm / cutline / n_body_slots / band / head_raise / border_class / verdict …，即全部非 note 事件）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIELDS = ("anchor", "bbox", "content_sha", "evidence", "fp", "product_version")


def classify(ev: dict) -> set[str]:
    a = (ev.get("target") or {}).get("anchor") or {}
    ed = a.get("evidence") or {}
    got = set()
    if a:
        got.add("anchor")
    if a.get("bbox") or a.get("quad"):
        got.add("bbox")
    if a.get("content_sha"):
        got.add("content_sha")
    if ed:
        got.add("evidence")
    if ed.get("fp"):
        got.add("fp")
    if ed.get("sha256") or ed.get("params_hash") or a.get("product_key"):
        got.add("product_version")
    return got


def book_of(ev: dict) -> str:
    t = ev.get("target") or {}
    return t.get("book") or str(t.get("key", "")).split(":")[0] or "?"


def scan(events_dir: Path) -> dict:
    tot: dict = defaultdict(lambda: defaultdict(int))
    for f in sorted(events_dir.glob("*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("kind") == "note":
                    continue
                b = tot[book_of(ev)]
                b["n"] += 1
                for k in classify(ev):
                    b[k] += 1
    return {b: dict(v) for b, v in sorted(tot.items())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--events-dir", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    d = args.events_dir
    if d is None:
        from open_guji_cv.core.workspace import feedback_root
        d = feedback_root() / "events"
    if not d.is_dir():
        print(f"没有事件目录：{d}", file=sys.stderr)
        return 1
    res = scan(d)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    print(f"{'书':<12}{'事件':>7}" + "".join(f"{k:>16}" for k in FIELDS))
    for b, v in res.items():
        n = v["n"]
        print(f"{b:<12}{n:>7}" + "".join(f"{v.get(k, 0):>9}({100 * v.get(k, 0) / n:4.0f}%)" for k in FIELDS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
