# -*- coding: utf-8 -*-
"""把各模型的 jsonl 输出（{cid, char, conf, basis}，一遍一个文件）合成 `utils/ry_group` 的答案表。

用法：python build_cache.py <out.json> <ctx.json> muse=a.jsonl,b.jsonl gemini=c.jsonl,d.jsonl haiku=e.jsonl
ctx.json：{cid: ctx_key}（由 seed_admit 同口径的前后文离线算出，见 `utils.ji_yi_si_clf.ctx_key`）。
缺的一遍记 None。"""
import json
import sys


def main(out, ctx_path, *specs):
    ctx = json.load(open(ctx_path, encoding="utf-8"))
    votes: dict = {c: {} for c in ctx}
    for sp in specs:
        model, files = sp.split("=", 1)
        for pi, fn in enumerate(files.split(",")):
            for line in open(fn, encoding="utf-8"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if r["cid"] in votes:
                    v = votes[r["cid"]].setdefault(model, [])
                    v += [None] * (pi - len(v))
                    v.append(r.get("char"))
    cells = {c: {"ctx": ctx[c], "ver": "ry-v2",
                 "votes": {m: (v + [None, None])[:2] if m != "haiku" else v for m, v in vs.items()}}
             for c, vs in votes.items()}
    json.dump({"cells": cells}, open(out, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main(*sys.argv[1:])
