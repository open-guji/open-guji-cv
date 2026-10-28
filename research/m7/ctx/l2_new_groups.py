"""新文意组的 L2 表（2026-10-24，A24「强化于千子干等形近判别」）：从离线回放（`replay_groups.py` 的输出）取补放入口的格，
出给模型的批；各模型跑完后按 `groups.l2_panel` 的规则合成 `group_clf/1` 表（从空表起：主模型 high 且强模型没以 high 反对 → 给字；
主模型不是 high 时，强模型 high 且第二模型同字 → 给字）。
  make   <回放 jsonl> <输出目录> [--size 40]      → <组>/<组>p_NN.txt、<组>/manifest.json、<组>/cells.json
  ingest <输出目录> <组> <表 json>                → 各模型输出在 <输出目录>/<组>/runs/<模型>/<批>.json
L1 已给字的格也进批（审计 L1；表里照样记下模型的票，但管线 L1 先判，表不起作用）。
"""
import argparse, json, random
from collections import defaultdict
from pathlib import Path

from open_guji_cv.groups.context import CTX_VER, WIDTH
from open_guji_cv.groups.ctx_l3 import parse_output
from open_guji_cv.groups.l2_panel import panel_merge
from open_guji_cv.groups.prompt_template import book_prompt_vars, build_batch_rendered
from open_guji_cv.groups.registry import FLOW_GROUPS

REPO = Path(__file__).resolve().parents[3]
ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["make", "ingest"]); ap.add_argument("pos", nargs="+")
ap.add_argument("--size", type=int, default=40)
ap.add_argument("--main", default="haiku"); ap.add_argument("--strong", default="opus"); ap.add_argument("--second", default="sonnet")
a = ap.parse_args()

if a.cmd == "make":
    rp, out = Path(a.pos[0]), Path(a.pos[1])
    by = defaultdict(list)
    for line in open(rp, encoding="utf-8"):
        r = json.loads(line)
        if r["mode"] in ("lift", "joint"):
            by[r["group"]].append(dict(id=r["id"], left=r["left"][-WIDTH:], right=r["right"][:WIDTH]))
    bv = book_prompt_vars()
    for g, rows in sorted(by.items()):
        d = out / g; d.mkdir(parents=True, exist_ok=True)
        random.Random(7).shuffle(rows)
        man, cells = {}, {}
        prompt = REPO / FLOW_GROUPS[g].config_dir / "prompt.md"
        for i in range(0, len(rows), a.size):
            name = f"{g}p_{i // a.size:02d}"; chunk = rows[i:i + a.size]
            (d / f"{name}.txt").write_text(build_batch_rendered(prompt, chunk, bv), encoding="utf-8")
            man[name] = [c["id"] for c in chunk]
            cells.update({c["id"]: [c["left"], c["right"]] for c in chunk})
        (d / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=0), encoding="utf-8")
        (d / "cells.json").write_text(json.dumps(cells, ensure_ascii=False, indent=0), encoding="utf-8")
        print(g, len(rows), "格", len(man), "批")
else:
    d, g, table = Path(a.pos[0]) / a.pos[1], a.pos[1], Path(a.pos[2])
    spec = FLOW_GROUPS[g]
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    cells = json.loads((d / "cells.json").read_text(encoding="utf-8"))
    runs = {}
    for m in (a.main, a.strong, a.second):
        r = {}
        for name in man:
            f = d / "runs" / m / f"{name}.json"
            if f.exists():
                r.update(parse_output(f.read_text(encoding="utf-8")))
        if r:
            runs[m] = r
    t = {"schema": "group_clf/1", "group": g, "ctx_ver": CTX_VER, "ver": f"{g}-l2-1", "models": [], "cells": {}}
    ctxs = {i: tuple(v) for i, v in cells.items()}
    n = panel_merge(t, runs, "".join(sorted(spec.members)), ctxs, main=a.main, strong=a.strong, second=a.second)
    t["panel"] = {"strong": a.strong, "second": a.second, "by": "A24 强化于千子干等形近判别 2026-10-24"}
    table.write_text(json.dumps(t, ensure_ascii=False, indent=0), encoding="utf-8")
    print(g, {m: len(r) for m, r in runs.items()}, "/", len(cells), dict(n))
