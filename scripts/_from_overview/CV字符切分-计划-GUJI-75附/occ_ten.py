"""GUJI-75 复评门槛数据（Enzo，GUJI-208dv）：十册「遮挡格里无 coord 的格」统计。只读快照产物。

用法：python3 occ_ten.py <根目录> vol01 vol02 ...   （<根目录>/<册>/products/<册>/{seed_admit,align_ref}/p*.json）
口径：遮挡格＝seed_admit 格的 doubts 含 `occluded`；有 coord＝align_ref.coord 里有这个 id 且 ref_char 非空；
coord 空格＝有 id 但 ref_char 为空；无 coord＝align_ref.coord 里没有这个 id。第 1 列＝题列（阅读序最右）。
待审＝admit 为 False 的格（含排除名单格）。
"""
import collections
import glob
import json
import re
import sys

root = sys.argv[1]
res = {}
for v in sys.argv[2:]:
    P = f"{root}/{v}/products/{v}"
    t = collections.Counter()
    pages = {}
    nocoord_pages = collections.Counter()
    nocoord_col1_pages = collections.Counter()
    nocoord_no_align = 0
    for f in sorted(glob.glob(P + "/seed_admit/p*.json")):
        p = int(re.search(r"p(\d+)\.json", f).group(1))
        sa = json.load(open(f))["seed_admit"]
        try:
            al = json.load(open(f.replace("seed_admit", "align_ref")))["align_ref"]
            cd = {c["id"]: c for c in al.get("coord") or []}
            has_al = True
        except Exception:
            cd, has_al = {}, False
        for col in sa["columns"]:
            for ch in col["chars"]:
                t["cells"] += 1
                if not ch["admit"]:
                    t["review"] += 1
                if "occluded" in (ch.get("doubts") or []):
                    t["occ"] += 1
                    pages[p] = pages.get(p, 0) + 1
                    c = cd.get(ch["id"])
                    if c is None:
                        t["occ_nocoord"] += 1
                        nocoord_pages[p] += 1
                        if col["col"] == 1:
                            t["occ_nocoord_col1"] += 1
                            nocoord_col1_pages[p] += 1
                        if not has_al:
                            nocoord_no_align += 1
                    elif not c["ref_char"]:
                        t["occ_blank"] += 1
                    else:
                        t["occ_ref"] += 1
    res[v] = dict(t, pages=dict(pages), nocoord_pages=dict(nocoord_pages), nocoord_col1_pages=dict(nocoord_col1_pages), n_pages=len(glob.glob(P + "/seed_admit/p*.json")), no_align=nocoord_no_align)
tot = collections.Counter()
for v, r in res.items():
    ratio = (r.get("occ_nocoord", 0) / r["review"] * 100) if r.get("review") else 0
    print(f"{v}: 页{r['n_pages']} 格{r['cells']} 待审{r['review']} 遮挡{r.get('occ',0)}(coord有字{r.get('occ_ref',0)}/空格{r.get('occ_blank',0)}/无coord{r.get('occ_nocoord',0)}，其中第1列{r.get('occ_nocoord_col1',0)}) 无coord占待审{ratio:.2f}% 遮挡页{r['pages']} 无coord页{r['nocoord_pages']}")
    for k in ("cells", "review", "occ", "occ_ref", "occ_blank", "occ_nocoord", "occ_nocoord_col1"):
        tot[k] += r.get(k, 0)
print("合计:", dict(tot))
json.dump(res, open(f"{root}/occ_ten.json", "w"), ensure_ascii=False)
