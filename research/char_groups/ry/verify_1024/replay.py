"""离线回放 ry/rm/mz 组流程：把 seed_admit 产物里组流程的改动撤回，再用现行规则＋L2 表重跑这三组。
ry_shape 的宽高比用产物留痕里记下的值（图没变），不取图。
用法：python replay.py <产物根> <输出 jsonl> [--tables DIR] [--rules-dir DIR] [--vols vol11,...]
输出每格一行：id ref orig{char,admit,dec,mode} new{char,admit,dec,why,trail} left right ratio
"""
import argparse, glob, json, os, sys
from pathlib import Path
from types import SimpleNamespace

import yaml
from open_guji_cv.products.kinds.recog import PageAdmit
import open_guji_cv.steps.seed_admit as sa
from open_guji_cv.groups import aspect, methods, flow as gflow
from open_guji_cv.groups.flow import FlowConfig, group_flow_pass, CHANNEL
from open_guji_cv.groups.context import WIDTH

ap = argparse.ArgumentParser()
ap.add_argument("prod"); ap.add_argument("out")
ap.add_argument("--data", default="/root/.guji-data/main/siku-zongmu")
ap.add_argument("--tables", default="")
ap.add_argument("--rules-dir", default="")
ap.add_argument("--vols", default="")
ap.add_argument("--groups", default="ry,rm,mz")
a = ap.parse_args()
G = tuple(a.groups.split(","))
TD = Path(a.tables or f"{a.data}/config/groups/l2")
tables = {g: str(TD / f"{g}.json") for g in G if (TD / f"{g}.json").exists()}
if a.rules_dir:
    gflow.rules_path = lambda g: Path(a.rules_dir) / g / "rules.yaml"
cp = yaml.safe_load(open(f"{a.data}/config/codepoints.yaml"))["codepoints"]
canon = lambda c: cp.get(c, c)

RATIO = {}
_judge = aspect.judge
aspect.judge = lambda img: (None, None) if RATIO.get(img) is None else (
    "日" if RATIO[img] <= aspect.LOW else "曰" if RATIO[img] >= aspect.HIGH else None, RATIO[img])

vols = a.vols.split(",") if a.vols else sorted(os.listdir(a.prod))
fo = open(a.out, "w", encoding="utf-8")
for v in vols:
    for f in sorted(glob.glob(f"{a.prod}/{v}/seed_admit/p*.json")):
        key = os.path.basename(f)[:-5]
        page = PageAdmit.model_validate(json.load(open(f))["seed_admit"])
        ar = json.load(open(f"{a.prod}/{v}/align_ref/{key}.json"))["align_ref"]
        amap = {c["id"]: (c.get("align_char"), c.get("align_op")) for c in ar.get("chars", [])} if ar.get("anchored") else {}
        coord = {c["id"]: c.get("ref_char") for c in ar.get("coord") or []}
        gm = json.load(open(f"{a.prod}/{v}/glyph_match/{key}.json"))["glyph_match"]
        mmap = {c["id"]: SimpleNamespace(**c) for col in gm["columns"] if col.get("ok", True) for c in col["chars"]}
        orig = {}
        later = {}
        LATER = {"rare_ref", "witness3", "seal", "coord_fallback", "rare_ref_coord"}
        for col in page.columns:
            for r in col.chars:
                if r.admit and r.channel in LATER:
                    later[r.id] = dict(char=r.char, channel=r.channel)
                    r.admit, r.channel = False, None
        # 撤回组流程改动（所有组）：补放 → 未放；改字 → 原字放行；降审 → 原通道放行
        for col in page.columns:
            for r in col.chars:
                ev = r.evidence or {}
                g = ev.get("group")
                if not g:
                    continue
                orig[r.id] = dict(char=r.char, admit=r.admit, dec=g.get("decision"), mode=g.get("mode"), gid=g.get("id"),
                                  why=g.get("why"), later_demote=(ev.get("demoted_from") or {}).get("by") not in (None, CHANNEL))
                for t in g.get("solvers") or []:
                    if t.get("solver") == "ry_shape":
                        RATIO[r.id] = t.get("ratio")
                d = g.get("decision")
                if d == "admit":
                    r.admit, r.channel, r.provenance = False, None, ""
                elif d == "fix":
                    fx = ev.get("fixed_from") or {}
                    r.char, r.channel = fx.get("char", r.char), fx.get("channel")
                    r.admit = True
                elif d == "demote":
                    df = ev.get("demoted_from") or {}
                    r.admit, r.channel = True, df.get("channel")
                    r.provenance = "match"
                r.doubts = [x for x in (r.doubts or []) if not str(x).startswith("group_flow_")]
                r.evidence = {k: x for k, x in ev.items() if k not in ("group",)}
        seq = [r for c in sorted(page.columns, key=lambda c: c.col) for r in sa.sort_by_reading(c.chars)
               if not (r.doubts and "excluded" in r.doubts)] if hasattr(sa, "sort_by_reading") else None
        if seq is None:
            from open_guji_cv.utils.jiazhu_order import sort_by_reading
            seq = [r for c in sorted(page.columns, key=lambda c: c.col) for r in sort_by_reading(c.chars)
                   if not (r.doubts and "excluded" in r.doubts)]
        ctxs = {}
        for i, r in enumerate(seq):
            ctxs[r.id] = (sa._clf_ctx(seq, amap, i, -1, WIDTH), sa._clf_ctx(seq, amap, i, 1, WIDTH))
        cfg = FlowConfig(groups=G, l2_tables=tables, l2_drift=2, joint=True, lift_ref_guard=True, canon=canon,
                         delta=0.03, min_cov=0.85)

        def blocked(r):
            m = mmap.get(r.id)
            guard = getattr(m, "guard", None)
            if guard in sa._GROUP_FLOW_OWN_GUARDS:
                guard = None
            ds = [d for d in (r.doubts or []) if isinstance(d, str) and d not in sa._GROUP_FLOW_OWN_DOUBTS]
            return sa._hard_blocked(ds, guard) or any(d in sa._GROUP_FLOW_HARD for d in ds)

        group_flow_pass(seq, amap, lambda cid: [tuple(x) for x in (getattr(mmap.get(cid), "candidates", None) or [])],
                        blocked, cfg, ctx_fn=lambda s, i, step: sa._clf_ctx(s, amap, i, step, WIDTH),
                        patch_fn=lambda cid: cid, canon=canon, veto_refs=coord)
        for r in seq:
            ng = (r.evidence or {}).get("group")
            o = orig.get(r.id)
            if not ng and not (o and o["gid"] in G) and not (r.id in later and (later[r.id]["char"] or "") in ("日","曰","目")):
                continue
            row = dict(id=r.id, ref=(amap.get(r.id) or (None,))[0], coord=coord.get(r.id), orig=o,
                       new=None if not ng else dict(char=r.char, admit=r.admit, dec=ng["decision"], why=ng["why"],
                                                    gid=ng["id"], mode=ng["mode"], trail=ng["solvers"],
                                                    doubts=[d for d in (r.doubts or []) if str(d).startswith("group_flow_")]),
                       later=later.get(r.id), left=ctxs[r.id][0], right=ctxs[r.id][1], ratio=RATIO.get(r.id),
                       cands=(getattr(mmap.get(r.id), "candidates", None) or [])[:3])
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(v, file=sys.stderr)
