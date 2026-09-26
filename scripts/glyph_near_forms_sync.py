# -*- coding: utf-8 -*-
"""体检里人判「形近 / 异体」的字对 → 形近字人裁表 `config/confusable_human.json`（任务书 H §四·5）。

    PYTHONPATH=. python scripts/glyph_near_forms_sync.py <工作区>... [--apply]

来源：`feedback/glyph_audit.py` 消费 `near_form` 裁决时追加的 `<工作区>/output/glyph_selfcheck/near_forms.jsonl`
（每行 `{"pair": [字, 字], "instance_id", "peer", "event", "ts"}`）。人说「两个都没错，只是像」——
正是 `confusable.HUMAN_TABLE` 要的东西（书上真会混的形近），匹配侧见到这一对就不下 same 断言。

为什么是脚本、不是 `confusable.py` 现读：`match._PARTNER` 在导入时就定死了，按工作区现读会让
「同一进程开两个工作区」的控制台各拿各的表还不自知；进表是一次看得见、进 git 的改动更稳。
表里原有的对不动；新对记 `sources` 里的事件，重复跑幂等。不加 `--apply` 只报告。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TABLE = REPO / "config" / "confusable_human.json"


def collect(workspaces: list[Path]) -> dict[str, list[str]]:
    """{两字对（按码点排）: [事件 id…]}；单字、同字、非汉字对跳过。"""
    out: dict[str, list[str]] = {}
    for ws in workspaces:
        f = ws / "output" / "glyph_selfcheck" / "near_forms.jsonl"
        if not f.exists():
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            d = json.loads(ln)
            a, b = (list(d.get("pair") or []) + ["", ""])[:2]
            if len(a) != 1 or len(b) != 1 or a == b:
                continue
            k = "".join(sorted((a, b)))
            ev = d.get("event") or ""
            if ev not in out.setdefault(k, []):
                out[k].append(ev)
    return out


def merge(table: dict, found: dict[str, list[str]]) -> list[str]:
    pairs = table.setdefault("pairs", {})
    srcs = table.setdefault("sources", {})
    added = []
    for k, evs in sorted(found.items()):
        have = k in pairs or k[::-1] in pairs
        if not have:
            pairs[k] = 1.0
            added.append(k)
        old = srcs.setdefault(k, [])
        for e in evs:
            if e and e not in old:
                old.append(e)
    table["n_pairs"] = len(pairs)
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workspaces", nargs="+", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--table", type=Path, default=TABLE)
    a = ap.parse_args()
    found = collect(a.workspaces)
    table = json.loads(a.table.read_text(encoding="utf-8"))
    added = merge(table, found)
    print(json.dumps({"near_form_pairs": len(found), "new_pairs": added}, ensure_ascii=False))
    if a.apply and (added or found):
        a.table.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
