# -*- coding: utf-8 -*-
"""实验十五：把实验十三（墨闸）和十四（VLM）的逐条结果合起来看。

 1. τ 的留出检验：按册分（vol01 训 / vol02 测，反之亦然），看 τ=0.08 是不是过拟合。
 2. 组合策略：ink_line<τ → 直线；否则 → {U-Net(turn=10) | VLM 多数票 | 现役}，三选一比。
 3. 高墨支路上 VLM vs U-Net 逐条对照。
"""
import argparse
import glob
import json
import re
from collections import Counter
from pathlib import Path

_ap = argparse.ArgumentParser()
_ap.add_argument("--dir", default=str(Path(__file__).parent),
                 help="放 exp13_out.txt / pvg.json / exp14_*_blind.json 的目录")
_ap.add_argument("--tol", type=float, default=6.0)
_a = _ap.parse_args()
S = Path(_a.dir)
T = _a.tol

# ── 读实验十三逐条 ──
rows = {}
pat = re.compile(r"^\s*(\S+)\s+v=(\w+)\s+ink=([\d.]+)\s+valley=([\d.]+)\s+\|\s+直线\s+([\d.]+)\s+现役\s+([\d.]+)\((\w+)\)\s+U-Net\s+([\d.\-]+)")
for ln in (S / "exp13_out.txt").read_text(encoding="utf-8").splitlines():
    m = pat.match(ln)
    if not m:
        continue
    cid, v, ink, val, es, ec, ck, eu = m.groups()
    rows[cid] = {"v": v, "ink": float(ink), "e_str": float(es), "e_cur": float(ec),
                 "e_unet": None if eu.strip() == "-" else float(eu), "book": cid.split(":")[0]}
print("实验十三逐条", len(rows))

# ── 读 VLM 缓存 → 多数票误差 ──
pvg = {r["id"]: r for r in json.load(open(S / "pvg.json", encoding="utf-8"))}
caches = {Path(p).stem: json.load(open(p, encoding="utf-8")) for p in glob.glob(str(S / "exp14_*_blind.json"))}


def pick(t, n):
    m = re.search(r"#\s*(\d+)", t or "") or re.search(r"(\d+)", t or "")
    k = int(m.group(1)) if m else None
    return k if k and 1 <= k <= n else None


for cid, r in rows.items():
    p = pvg[cid]
    errs = [c[1] for c in p["cands"]]
    votes = [pick(c.get(cid, {}).get("text"), p["n_cand"]) for c in caches.values()]
    votes = [x for x in votes if x]
    r["e_vlm"] = errs[Counter(votes).most_common(1)[0][0] - 1] if votes else None
    r["e_vlm_max"] = None
    mx = caches.get("exp14_qwen_qwenvlmax_blind", {})
    k = pick(mx.get(cid, {}).get("text"), p["n_cand"])
    r["e_vlm_max"] = errs[k - 1] if k else None


def policy(r, tau, branch):
    if r["ink"] < tau:
        return r["e_str"]
    return {"unet": r["e_unet"], "vlm": r["e_vlm"], "vlmmax": r["e_vlm_max"], "cur": r["e_cur"]}[branch]


def hits(sub, tau, branch):
    es = [policy(r, tau, branch) for r in sub]
    return sum(1 for e in es if e is not None and e <= T), len(sub)


print("\n=== 1. τ 留出检验（按册） ===")
for train, test in (("vol01", "vol02"), ("vol02", "vol01")):
    tr = [r for r in rows.values() if r["book"] == train]
    te = [r for r in rows.values() if r["book"] == test]
    best = max((0.03, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12, 0.15), key=lambda t: hits(tr, t, "unet")[0])
    h_tr = hits(tr, best, "unet"); h_te = hits(te, best, "unet")
    c_tr = sum(1 for r in tr if r["e_cur"] <= T); c_te = sum(1 for r in te if r["e_cur"] <= T)
    print(f"  训 {train}(n={len(tr)}) 最优 τ={best:.2f} 训集 {h_tr[0]}/{h_tr[1]}（现役 {c_tr}）→ 测 {test}(n={len(te)}) {h_te[0]}/{h_te[1]}（现役 {c_te}）")
print("  （vol01 金标以 ok 为主、vol02 以 moved 为主，两册互为对方的『另一半』分布）")

print("\n=== 2. 组合策略总表（n=62，≤6px 命中）===")
allr = list(rows.values())
print(f"  现役                      {sum(1 for r in allr if r['e_cur']<=T)}/62")
for tau in (0.05, 0.08, 0.10):
    for br, name in (("cur", "否则现役"), ("unet", "否则U-Net(turn10)"), ("vlm", "否则VLM三票"), ("vlmmax", "否则VLM-max")):
        h, n = hits(allr, tau, br)
        print(f"  ink<{tau:.2f}→直线, {name:16s} {h}/{n}")

print("\n=== 3. 高墨支路（ink≥0.08）逐条：U-Net vs VLM三票 vs 现役 ===")
hi = sorted([r for r in allr if r["ink"] >= 0.08], key=lambda r: r["ink"])
cu = cv = cc = 0
for cid, r in ((k, v) for k, v in rows.items() if v["ink"] >= 0.08):
    eu, ev, ec = r["e_unet"], r["e_vlm"], r["e_cur"]
    cu += eu is not None and eu <= T; cv += ev is not None and ev <= T; cc += ec <= T
    f = lambda e: "  -  " if e is None else f"{e:5.1f}"
    print(f"  {cid:18s} v={r['v']:5s} ink={r['ink']:.3f} | U-Net {f(eu)} VLM {f(ev)} 现役 {f(ec)}")
print(f"  高墨支路 n={len(hi)}：U-Net {cu}  VLM三票 {cv}  现役 {cc}")

print("\n=== 4. 低墨支路（ink<0.08）里直线错的（闸会放过的）===")
for cid, r in rows.items():
    if r["ink"] < 0.08 and r["e_str"] > T:
        print(f"  {cid:18s} v={r['v']} ink={r['ink']:.3f} 直线 {r['e_str']:.0f} U-Net {r['e_unet']} VLM {r['e_vlm']} 现役 {r['e_cur']:.0f}")
