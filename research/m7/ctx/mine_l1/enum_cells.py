"""枚举 vol04–20 产物里与 于千子干予官宫兩雨侯候 有关的格。"""
import glob, json, sys
from pathlib import Path
from types import SimpleNamespace
from open_guji_cv.steps.seed_admit import _clf_ctx
from open_guji_cv.utils.jiazhu_order import sort_by_reading
T = set("于千子干予官宫兩雨侯候")
root = Path(sys.argv[1]); out = open(sys.argv[2], "w", encoding="utf-8")
for vd in sorted(root.glob("vol*")):
    if not vd.is_dir(): continue
    for f in sorted((vd / "seed_admit").glob("p*.json")):
        d = json.load(open(f, encoding="utf-8"))["seed_admit"]
        af = vd / "align_ref" / f.name; gf = vd / "glyph_match" / f.name
        amap = {c["id"]: (c["align_char"], c.get("align_op")) for c in json.load(open(af))["align_ref"]["chars"]} if af.exists() else {}
        gm = {c["id"]: c for col in json.load(open(gf))["glyph_match"]["columns"] for c in col["chars"]} if gf.exists() else {}
        raw = {c["id"]: c for col in d["columns"] for c in col["chars"]}
        seq = [SimpleNamespace(**{k: c.get(k) for k in ("id", "char", "admit", "doubts", "slot", "sub")})
               for col in sorted(d["columns"], key=lambda c: c["col"])
               for c in sort_by_reading([SimpleNamespace(**cc) for cc in col["chars"]]) for c in [raw[c.id]]
               if not (c.get("doubts") and "excluded" in c["doubts"])]
        for i, r in enumerate(seq):
            c = raw[r.id]; g = gm.get(r.id, {}); cands = g.get("candidates") or []
            ref = (amap.get(r.id) or (None, None))[0]
            close = [ch for ch, v in cands if cands and cands[0][1] - v < 0.03]
            if not (T & ({ref, c.get("char")} | set(close))): continue
            grp = (c.get("evidence") or {}).get("group") or {}
            out.write(json.dumps(dict(id=r.id, vol=vd.name, admit=c["admit"], char=c.get("char"), channel=c.get("channel"),
                prov=c.get("provenance"), doubts=c.get("doubts"), cands=cands[:5], guard=g.get("guard"), ref=ref,
                op=(amap.get(r.id) or (None, None))[1], group=grp.get("id"), gmode=grp.get("mode"), gdec=grp.get("decision"),
                gsolv=grp.get("solvers"), left=_clf_ctx(seq, amap, i, -1, 20), right=_clf_ctx(seq, amap, i, 1, 20)), ensure_ascii=False) + "\n")
