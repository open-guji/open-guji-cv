"""把 `_resolve_ji_yi_si` 在快照的 seed_admit 产物上回放，开/关 ji_yi_si_ctx_rule 各一遍（overview#428）。
只看本族格：放行数、送审数、对强真值的错数。快照里已是 resolve 之后的结果，所以「关」= 再跑一遍现行规则（幂等）。
用法：python replay_rule.py <snap_root> <items.jsonl>"""
import copy, glob, json, os, sys
from collections import Counter
from open_guji_cv.products.kinds.recog import PageAdmit
import open_guji_cv.steps.seed_admit as sa
SNAP, ITEMS = sys.argv[1], sys.argv[2]
BOOKS = {"vol02": ("vol02_20260930T0339", "vol02_20260929T1024"),
         "vol03": ("vol03_20260930T0457", "vol03_20260928T1708-full"),
         "vol04": ("vol04_20261006T0716", "vol04_20261006T0716")}
gold = {}
for l in open(ITEMS, encoding="utf-8"):
    r = json.loads(l)
    if r["group"] == "jys" and r["gold"] in ("己", "已", "巳") and r["gold_src"] not in (None, "witness_agree"):
        gold[r["id"]] = (r["gold"], r["gold_src"])
J = set("己已巳")
for bk, (s_seed, s_up) in BOOKS.items():
    res = {"关": Counter(), "开": Counter()}
    for f in sorted(glob.glob(f"{SNAP}/{s_seed}/products/{bk}/seed_admit/p*.json")):
        key = os.path.basename(f)[:-5]
        page = PageAdmit.model_validate(json.load(open(f))["seed_admit"])
        ar = json.load(open(f"{SNAP}/{s_up}/products/{bk}/align_ref/{key}.json"))["align_ref"]
        amap = {c["id"]: (c.get("align_char"), c.get("align_op")) for c in ar.get("chars", [])}
        for mode, kw in (("关", {}), ("开", {"ctx_rule": (0.98, 5)})):
            cols = copy.deepcopy(page.columns)
            # 只重放本族格：先记下本族格的 id（人裁位 resolve 自己会跳过）
            sa._resolve_ji_yi_si(cols, amap, {}, {}, False, **kw)
            for cc in cols:
                for r in cc.chars:
                    if (r.char or "") in J or r.id in gold or "ji_yi_si_ctx_review" in (r.doubts or []):
                        if r.channel == "human":
                            continue
                        c = res[mode]
                        if not ((r.char or "") in J or "ji_yi_si_ctx_review" in (r.doubts or [])):
                            continue
                        c["格"] += 1
                        c["放行" if r.admit else "送审"] += 1
                        if r.id in gold:
                            c["真值格"] += 1
                            c["真值错" if (not r.admit or r.char != gold[r.id][0]) and r.admit else ("真值送审" if not r.admit else "真值对")] += 1
    print(bk, {k: dict(v) for k, v in res.items()})
