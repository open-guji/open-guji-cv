"""日曰（ry）＋日目（rm）L2 表补细读票（A24 2026-10-24）。

输入：中心库现行表、逐格细读（dataset `char-groups/variant/ry/labels.jsonl`：每格 id、form、conf、依据、原标签、事件号、建表窗口 left/right）、
补跑的 haiku 一遍（`haiku.json`，ry 提示词，只补表里没有 haiku 票的格）。
输出：新表 `<out>/ry.json`、`<out>/rm.json`（ver 加 `+v1024`），规则见 `ctx_l2.add_verify`。
细读的字映射到各组：ry 组 日／曰 照写、目和别的字记「其他」；rm 组 日／目 照写、曰和别的字记「其他」。
用法：python build_tables.py <中心库 l2 目录> labels.jsonl haiku_1024.json <out>
"""
import json
import sys
from pathlib import Path

from open_guji_cv.groups.ctx_l2 import OTHER, add_verify
from open_guji_cv.groups.context import WIDTH, ctx_key

MODEL = "opus"
src, vpath, hpath, out = sys.argv[1:5]
vs = [json.loads(l) for l in open(vpath, encoding="utf-8")]
for v in vs:
    v.setdefault("char", v.get("form"))          # dataset labels.jsonl 用 form
h = json.load(open(hpath, encoding="utf-8"))
haiku = {e["id"]: e for e in (h["cells"] if isinstance(h, dict) else h)}
ctxs = {v["id"]: (v["left"] or "", v["right"] or "") for v in vs}
Path(out).mkdir(parents=True, exist_ok=True)
for g, members in (("ry", "日曰"), ("rm", "日目")):
    t = json.load(open(Path(src) / f"{g}.json", encoding="utf-8"))
    cells = t["cells"]
    nh = 0
    if g == "ry":
        for cid, h in haiku.items():
            e = cells.get(cid)
            if e is not None and (e.get("votes") or {}).get("haiku"):
                continue
            if e is None:
                left, right = ctxs[cid]
                ok = h["char"] in members and h["conf"] in ("high", "mid")
                e = cells[cid] = {"ctx": ctx_key(left[-WIDTH:], right[:WIDTH]), "char": h["char"] if ok else None,
                                  "why": "agree" if ok else "abstain:other" if h["char"] == OTHER else "abstain:low_conf",
                                  "votes": {}}
            e.setdefault("votes", {})["haiku"] = [h["char"], h["conf"]]
            nh += 1
    run = {}
    for v in vs:
        if v["char"] is None:
            continue
        ch = v["char"] if v["char"] in members else OTHER
        run[v["id"]] = {"char": ch, "conf": v["conf"]}
    n = add_verify(t, MODEL, run, members, ctxs)
    t["ver"] = t["ver"].split("+")[0] + "+v1024"
    json.dump(t, open(Path(out) / f"{g}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(g, "haiku", nh, n, file=sys.stderr)
