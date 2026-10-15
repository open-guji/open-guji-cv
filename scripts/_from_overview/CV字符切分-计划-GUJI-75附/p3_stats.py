"""GUJI-75 首查（Enzo，GUJI-208cb）：vol02 p3 印章页的量化。只读快照产物，不改任何东西。

用法：
  # 快照分支在 guji-workspace 仓；只取需要的步骤目录
  git fetch --depth=1 origin snap/96mid1ogzk/vol02/20260929T1024      # Step5-7（align_ref／seed_admit）
  git archive FETCH_HEAD products/vol02/align_ref products/vol02/seed_admit | tar -x -C $D1   # 全册（188 页），末段「全册」口径靠它
  git fetch --depth=1 origin snap/96mid1ogzk/vol02/20261006T2101      # 10-06 交付态（人裁后）seed_admit
  git show FETCH_HEAD:products/vol02/seed_admit/p0003.json > $D2/sa_1006_p3.json
  python3 p3_stats.py $D1/products/vol02 $D2/sa_1006_p3.json
"""
import collections
import glob
import json
import re
import sys

P, F1006 = sys.argv[1], sys.argv[2]
al = json.load(open(f"{P}/align_ref/p0003.json"))["align_ref"]
sa0 = json.load(open(f"{P}/seed_admit/p0003.json"))["seed_admit"]
sa1 = json.load(open(F1006))["seed_admit"]
coord = {c["id"]: c for c in al["coord"]}
print("p3 对位：anchored=%s 票数=%s coord_cols=%s coord_fallback=%s" % (al["anchored"], al["n_votes"], al["coord_cols"], al["coord_fallback"]))

old = {ch["id"]: (col["col"], ch) for col in sa0["columns"] for ch in col["chars"]}
new = {ch["id"]: (col["col"], ch) for col in sa1["columns"] for ch in col["chars"]}
print("格数 09-29=%d 10-06=%d 共有=%d" % (len(old), len(new), len(set(old) & set(new))))

c = collections.Counter()
percol = collections.defaultdict(collections.Counter)
for i, (cn, ch) in old.items():
    occ = "occluded" in (ch.get("doubts") or [])
    k = "admit" if ch["admit"] else "review"
    c[k] += 1
    cc = coord.get(i)
    kind = "非遮挡" if not occ else ("无coord" if cc is None else ("coord空格" if not cc["ref_char"] else "coord有字"))
    c[(k, kind)] += 1
    percol[cn][kind] += 1
for k, v in sorted(c.items(), key=str):
    print("  ", k, v)
print("按列：")
for cn in sorted(percol):
    print("  col", cn, dict(percol[cn]))

# coord 默认字 vs 10-06 人裁后的字
res = collections.Counter()
bad = []
for i, (cn, ch) in old.items():
    if "occluded" not in (ch.get("doubts") or []):
        continue
    n = new[i][1]
    cc = coord.get(i)
    kind = "no_coord" if cc is None else ("blank" if not cc["ref_char"] else "ref")
    if not n["admit"]:
        res[kind + "_10-06仍待审"] += 1
        continue
    truth = n.get("char")
    if kind == "ref":
        ok = truth == cc["ref_char"]
        res["ref_" + ("同字" if ok else "不同字")] += 1
        if not ok:
            bad.append((i, cc["ref_char"], truth, n.get("channel")))
    elif kind == "blank":
        res["blank_" + ("人填了字" if truth else "判非字")] += 1
    else:
        res["no_coord_人裁通道=" + str(n.get("channel"))] += 1
print("coord 默认字 vs 10-06：", dict(res), "不同字:", bad)

# 全册 coord 与最终放行字一致率（只数有 coord 字且已放行有字的格）
tot = collections.Counter()
dis = []
for f in sorted(glob.glob(P + "/seed_admit/p*.json")):
    p = int(re.search(r"p(\d+)\.json", f).group(1))
    s = json.load(open(f))["seed_admit"]
    a = json.load(open(f.replace("seed_admit", "align_ref")))["align_ref"]
    cd = {x["id"]: x for x in a.get("coord") or []}
    if not a["anchored"]:
        tot["未锚页"] += 1
    for col in s["columns"]:
        for ch in col["chars"]:
            tot["cells"] += 1
            tot["review" if not ch["admit"] else "admit"] += 1
            x = cd.get(ch["id"])
            if x and x["ref_char"] and ch["admit"] and ch.get("char"):
                tot["coord比对"] += 1
                if x["ref_char"] == ch["char"]:
                    tot["一致"] += 1
                else:
                    dis.append((ch["id"], ch["char"], x["ref_char"], ch.get("channel")))
print("全册：", dict(tot), "不一致通道分布：", dict(collections.Counter(d[3] for d in dis)))
