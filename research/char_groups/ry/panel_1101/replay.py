"""离线回放 ry/rm/mz/jys 在现行代码（含 L3 二审小组）下的结论（A24 2026-11-01，GUJI-563 压低日曰日目己已巳送审）。

做法：把 seed_admit 产物里字组流程的改动撤回（补放→未放、改字→原字、降审→原通道放行），再用现行 `sa._group_flow_pass`
（真配置：L1 规则、L3 答案表、L2 模型、L3 在线＋二审小组）重跑。图不取：ry_shape 的宽高比用产物留痕里记下的值。
用法：python replay.py <产物根> <输出.jsonl> --ids <待审格号文件，一行一个> [--no-panel]
需要：GUJI_WORKSPACE 指向工作区（db pull 过）、GUJI_ANTHROPIC_API_KEY（L3 在线真问；问过的存进本机 feedback/rulings，不推库）。
输出每格一行：id ref orig{...} new{char,admit,dec,why,trail} left right。
"""
import argparse, json, os, sys
from pathlib import Path
from types import SimpleNamespace

import yaml
import open_guji_cv.steps.seed_admit as sa
from open_guji_cv.products.kinds.recog import PageAdmit
from open_guji_cv.groups import aspect, methods
from open_guji_cv.groups.flow import CHANNEL
from open_guji_cv.groups.context import WIDTH
from open_guji_cv.groups.protocol import GroupVerdict

ap = argparse.ArgumentParser()
ap.add_argument("prod"); ap.add_argument("out"); ap.add_argument("--ids", required=True)
ap.add_argument("--no-panel", action="store_true")
ap.add_argument("--data", default="/root/.guji-data/main/siku-zongmu")
a = ap.parse_args()

want = [l.strip() for l in open(a.ids, encoding="utf-8") if l.strip()]
pages = {}
for i in want:
    v, pg = i.split(":")[:2]
    pages.setdefault((v, int(pg)), set()).add(i)

cp = yaml.safe_load(open(f"{a.data}/config/codepoints.yaml"))["codepoints"]
canon = lambda c: cp.get(c, c)
p = sa.SeedAdmitParams().model_copy(update={"group_flow": ("ry", "rm", "mz", "jys")})      # 只回放文意四组（其余字形组要取图）
if a.no_panel:
    p = p.model_copy(update={"group_flow_llm_panel": ()})
ctx = SimpleNamespace(book=SimpleNamespace(canonical_char=canon, codepoints=cp))

RATIO, COORD = {}, {}
def _shape(inp, img):
    r = RATIO.get(inp.cell_id)
    ch, rat = (None, None) if r is None else ("日" if r <= aspect.LOW else "曰" if r >= aspect.HIGH else None, r)
    ok = ch in inp.members
    conf = None if rat is None else (aspect.LOW - rat if ch == "日" else rat - aspect.HIGH if ch == "曰" else 0.0) * 5
    return GroupVerdict(ch if ok else None, conf=conf if ok else 0.0, why="agree" if ok else "abstain:aspect", via="ry_shape",
                        extra={"ratio": None if rat is None else round(float(rat), 3)})
object.__setattr__(methods.RY_SHAPE, "fn", _shape)
sa._page_patch = lambda src, page, col, slot, sub: object()
sa._coord_refs = lambda c, page, cache: COORD

fo = open(a.out, "w", encoding="utf-8")
for (v, pg), ids in sorted(pages.items()):
    key = f"p{pg:04d}"
    f = f"{a.prod}/{v}/seed_admit/{key}.json"
    if not os.path.exists(f):
        print("缺", f, file=sys.stderr); continue
    page = PageAdmit.model_validate(json.load(open(f))["seed_admit"])
    ar = json.load(open(f"{a.prod}/{v}/align_ref/{key}.json"))["align_ref"]
    amap = {c["id"]: (c.get("align_char"), c.get("align_op")) for c in ar.get("chars", [])} if ar.get("anchored") else {}
    COORD.clear(); COORD.update({c["id"]: c.get("ref_char") for c in ar.get("coord") or []})
    gm = json.load(open(f"{a.prod}/{v}/glyph_match/{key}.json"))["glyph_match"]
    mmap = {c["id"]: SimpleNamespace(**c) for col in gm["columns"] if col.get("ok", True) for c in col["chars"]}
    orig = {}
    for col in page.columns:
        for r in col.chars:
            ev = r.evidence or {}
            g = ev.get("group")
            if not g:
                continue
            orig[r.id] = dict(char=r.char, admit=r.admit, dec=g.get("decision"), mode=g.get("mode"), gid=g.get("id"), why=g.get("why"))
            for t in g.get("solvers") or []:
                if t.get("solver") == "ry_shape" and t.get("ratio") is not None:
                    RATIO[r.id] = t["ratio"]
            d = g.get("decision")
            if d in ("admit", "provisional"):
                if d == "provisional" and (ev.get("fixed_from")):
                    fx = ev["fixed_from"]; r.char, r.channel = fx.get("char", r.char), fx.get("channel"); r.admit = True
                else:
                    r.admit, r.channel, r.provenance = False, None, ""
            elif d == "fix":
                fx = ev.get("fixed_from") or {}
                r.char, r.channel = fx.get("char", r.char), fx.get("channel"); r.admit = True
            elif d == "demote":
                df = ev.get("demoted_from") or {}
                r.admit, r.channel = True, df.get("channel"); r.provenance = "match"
            r.doubts = [x for x in (r.doubts or []) if not str(x).startswith("group_flow_")]
            r.evidence = {k: x for k, x in ev.items() if k != "group"}
    sa._group_flow_pass(p, page.columns, amap, mmap, ctx=ctx, page=pg, patch_missing=None)
    for col in page.columns:
        for r in col.chars:
            if r.id not in ids:
                continue
            ng = (r.evidence or {}).get("group")
            fo.write(json.dumps(dict(id=r.id, ref=(amap.get(r.id) or (None,))[0], orig=orig.get(r.id),
                                     new=None if not ng else dict(char=r.char, admit=r.admit, dec=ng["decision"], why=ng["why"], gid=ng["id"],
                                                                  mode=ng["mode"], trail=ng["solvers"],
                                                                  doubts=[d for d in (r.doubts or []) if str(d).startswith("group_flow_")])),
                                 ensure_ascii=False) + "\n")
    print(v, pg, file=sys.stderr, flush=True)
print("usage", json.dumps(__import__("open_guji_cv.groups.ctx_llm", fromlist=["x"]).usage_summary()), file=sys.stderr)
