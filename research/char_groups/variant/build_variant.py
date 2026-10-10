"""异体组（variant）建集：overview#437 CV 经理 10-09 22:55 派给道 B。

用法：python build_variant.py <outdir> --prod <dir:vol04=..,vol05=..> [--noabs vol04产物目录]
读：沙箱里重放出的 seed_admit 产物（`<prod>/<book>/seed_admit/p*.json`）、工作区看图结论/整理看图判定、
dataset 里的 gold2/人裁。写：<outdir>/items.jsonl、baseline.json（crops 另由 crops.py 取）。
不改任何 Step、不碰各册 products。
"""
import argparse, collections, glob, json, os, sys

WS = os.environ.get("GUJI_WORKSPACE", "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本")
sys.path.insert(0, "/home/user/open-guji-cv")
from open_guji_cv.variants import are_variants          # 关系层（带来源标签；只当先验）


def cells(prod, book):
    out = {}
    for f in sorted(glob.glob(f"{prod}/{book}/seed_admit/p*.json")):
        for c in json.load(open(f))["seed_admit"]["columns"]:
            for x in c["chars"]:
                out[x["id"]] = x
    return out


def labels(book, dec_dir=None, gold2=None):
    """truth[id] = (字, 档, 来源)；人裁 > gold2 看图 > 看图结论 > 整理看图 batch。"""
    lab = {}
    def put(i, ch, tier, src, w=0):
        if i not in lab or lab[i][3] <= w:
            lab[i] = (ch, tier, src, w)
    p = f"{WS}/reports/{book}/看图结论.jsonl"
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            d = json.loads(l)
            ch = d.get("char") if d.get("v") == "wrong" and d.get("char") else (d.get("shown") if d.get("v") == "ok" else None)
            if ch: put(d["cell"], ch, "B_vision", "vision_event", 1)
    if gold2 and os.path.exists(gold2):
        for l in open(gold2, encoding="utf-8"):
            d = json.loads(l)
            ch = d.get("char") if d.get("v") == "wrong" and d.get("char") else (d.get("shown") if d.get("v") == "ok" else None)
            if not ch: continue
            if d.get("src") == "用户": put(d["cell"], ch, "A_human", "human_review", 3)
            else: put(d["cell"], ch, "B_vision", "gold2_look", 2)
    if dec_dir:
        for f in sorted(glob.glob(dec_dir + "/b*.json")):
            for k, v in json.load(open(f))["confirmed"].items():
                put(k, v["char"], "B_vision", "zl_look_" + v["kind"], 2)
    return lab


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--prod", nargs="+", required=True)
    ap.add_argument("--noabs", default=None); ap.add_argument("--dec", default=None)
    ap.add_argument("--gold2", nargs="*", default=[])
    a = ap.parse_args()
    prod = dict(p.split("=") for p in a.prod)
    g2 = dict(p.split("=") for p in a.gold2)
    os.makedirs(a.out, exist_ok=True)
    items = {}
    def add(i, book, src, pair, **kw):
        _, p, c, s = i.split(":"); sub = s[-1] if s and not s.lstrip("-").isdigit() else None
        it = items.setdefault(i, {"id": i, "book": book, "page": int(p), "col": int(c), "slot": int(s.rstrip("ab")), "sub": sub,
                                  "group": "variant", "sources": [], "pairs": []})
        if src not in it["sources"]: it["sources"].append(src)
        if pair and list(pair) not in it["pairs"]: it["pairs"].append(list(pair))
        it.update({k: v for k, v in kw.items() if v is not None})
    allc = {}
    for book, d in prod.items():
        cs = cells(d, book); allc[book] = cs
        lab = labels(book, a.dec if book == "vol05" else None, g2.get(book))
        for i, x in cs.items():
            ev = x.get("evidence") or {}
            ls = ev.get("lane_skip")
            if ls:       # #433 护栏：别把刻本异体改成通用字
                form = ls.get("form") or ls.get("lib"); ch = ls.get("char") or x["char"]
                add(i, book, "lane_variant_guard:" + ls.get("why", ""), (form, ch), lane=ls.get("lane"), why=ls.get("why"))
        for i, (ch, tier, src, _) in lab.items():
            x = cs.get(i)
            if x is None: continue
            if src.endswith("variant_identity"):       # 整理看图标「异体同字」：默认字与真值是异体对
                add(i, book, "zl_look_variant_identity", (x["char"], ch))
            elif x["char"] and ch != x["char"] and are_variants(x["char"], ch):
                add(i, book, "label_variant_diff", (x["char"], ch))
        a_book = a.noabs if (a.noabs and book == "vol04") else None
        if a_book:
            na = cells(a_book, book)
            for i, x in cs.items():
                y = na.get(i)
                if y and x["admit"] and not y["admit"] and any("shadow_veto" in d for d in (y.get("doubts") or [])):
                    pk = ((y.get("evidence") or {}).get("shadow_veto") or {}).get("pick")
                    add(i, book, "shadow_veto_abstained(#431)", (x["char"], pk) if pk else None)
        for i, it in items.items():
            if it["book"] != book: continue
            x = cs.get(i, {})
            t = lab.get(i)
            it.update({"admit": x.get("admit"), "channel": x.get("channel"), "char": x.get("char"),
                       "provenance": x.get("provenance"), "doubts": x.get("doubts"),
                       "gold": t[0] if t else None, "gold_tier": t[1] if t else None, "gold_src": t[2] if t else None,
                       "gold_equals_admit": (t[0] == x.get("char")) if t and x.get("admit") else None,
                       "gold_variant_of_admit": (t[0] != x.get("char") and are_variants(t[0], x.get("char") or "")) if t and x.get("char") else None})
    with open(a.out + "/items.jsonl", "w", encoding="utf-8") as f:
        for it in sorted(items.values(), key=lambda z: (z["book"], z["page"], z["col"], z["slot"])):
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    # 基线
    base = {}
    for book, cs in allc.items():
        its = [it for it in items.values() if it["book"] == book]
        lab = labels(book, a.dec if book == "vol05" else None, g2.get(book))
        adm_lab = [(i, x, lab[i]) for i, x in cs.items() if x["admit"] and i in lab and x["char"]]
        wrong = [(i, x["char"], t[0]) for i, x, t in adm_lab if t[0] != x["char"]]
        wv = [w for w in wrong if are_variants(w[1], w[2])]
        by_src = collections.defaultdict(lambda: collections.Counter())
        for it in its:
            for s in it["sources"]:
                k = s.split(":")[0]
                by_src[k]["cells"] += 1
                by_src[k]["admit" if it.get("admit") else "pending"] += 1
                if it.get("gold") and it.get("admit"):
                    by_src[k]["admit_with_truth"] += 1
                    if it["gold"] != it["char"]: by_src[k]["admit_wrong"] += 1
        base[book] = {"cells_total": len(cs), "admit": sum(x["admit"] for x in cs.values()),
                      "variant_item_cells": len(its), "by_source": {k: dict(v) for k, v in by_src.items()},
                      "labelled_admit": len(adm_lab), "labelled_admit_wrong": len(wrong),
                      "labelled_admit_wrong_variant": len(wv), "wrong_variant_ids": [f"{i} 放{c}→真{t}" for i, c, t in wv],
                      "wrong_other_ids": [f"{i} 放{c}→真{t}" for i, c, t in wrong if (i, c, t) not in wv]}
    json.dump(base, open(a.out + "/baseline.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({b: {k: v for k, v in d.items() if "ids" not in k} for b, d in base.items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
