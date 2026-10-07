"""质量闸 + 「非组内」类（Z-rr 第二步，overview#442）。
质量闸：字块噪声（贴边长线、散斑）→ 不给字。非组内：第 4 类「其他」，负例＝外围格（库/上下文把它们放进组、实际是 久火尺今又）与 core 里放行字、整理本都不在组内的格；
训练正例同前（弱标签 dev+pool，不含强真值与 vol04）。负例太少（~43），用 5 折在负例上交叉评。"""
import json, collections, warnings, os
import numpy as np, cv2
from feat import *
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import KFold
warnings.filterwarnings("ignore")

def quality(path):
    b = binarize(path)
    if b is None: return None
    h, w = b.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n <= 1: return dict(noise=1.0, line=1, edge=1.0)
    areas = st[1:, cv2.CC_STAT_AREA]; tot = areas.sum()
    main = areas.max()
    keep = [i + 1 for i, a in enumerate(areas) if a >= 0.08 * main]
    kept = areas[[k - 1 for k in keep]].sum()
    line = 0
    for i in range(1, n):
        x, y, cw, ch, a = st[i]
        touches = x == 0 or y == 0 or x + cw == w or y + ch == h
        if touches and a >= 0.02 * main and (max(cw, ch) / max(1, min(cw, ch)) >= 6) : line = 1
    edge = float((b[:3].sum() + b[-3:].sum() + b[:, :3].sum() + b[:, -3:].sum())) / max(1, b.sum())
    return dict(noise=1 - kept / tot, line=line, edge=edge)

def gated(q, noise_thr=0.12, edge_thr=0.12):
    return q is None or q["line"] == 1 or q["noise"] > noise_thr or q["edge"] > edge_thr

R = [r for r in load_items(core_only=False) if r["split"] != "extra" and os.path.exists(crop_path(r))]
F, Q = {}, {}
for r in R:
    f = features(crop_path(r)); q = quality(crop_path(r))
    if f is not None: F[r["id"]] = f[0]
    Q[r["id"]] = q
strong = lambda r: r["gold_tier"] in ("A_human", "B_vision") and r["gold"] in CLS
weak = lambda r: r["core"] and r["gold_tier"] == "C_weak" and r["char"] in CLS
TRAIN = {"vol02", "vol03", "vol05", "vol06", "vol07", "vol08", "vol09", "vol10"}
pos = [r for r in R if weak(r) and r["book"] in TRAIN and r["id"] in F]
neg = [r for r in R if r["id"] in F and (r["char"] or "") not in CLS and ((r["ref"] or "") not in CLS or not r["core"])]
print("正例", len(pos), "负例", len(neg), collections.Counter(r["char"] for r in neg).most_common(6))
mk = lambda: RandomForestClassifier(300, min_samples_leaf=2, class_weight="balanced", random_state=0, n_jobs=-1)
Xp = np.array([F[r["id"]] for r in pos]); yp = [CLS.index(r["char"]) for r in pos]
def fit(negs):
    X = np.vstack([Xp] + ([np.array([F[r["id"]] for r in negs])] if negs else []))
    y = yp + [3] * len(negs); m = mk(); m.fit(X, y); return m
def decide(p, thr):
    return CLS[int(p[:3].argmax())] if (p.argmax() != 3 and p.max() >= thr) else None   # None＝弃权（含判为「其他」）

# 负例：5 折，每折用其余负例训练
negP = {}
for tr_i, te_i in KFold(5, shuffle=True, random_state=0).split(neg):
    m = fit([neg[i] for i in tr_i])
    for i in te_i: negP[neg[i]["id"]] = m.predict_proba(F[neg[i]["id"]].reshape(1, -1))[0]
m_all = fit(neg)
print("\n[非组内负例 5 折] 被拦下（弃权/判其他）：")
for thr in (0.5, 0.8):
    wrong = [(r["id"], r["char"], decide(negP[r["id"]], thr)) for r in neg if decide(negP[r["id"]], thr)]
    print(f" thr{thr}: 拦下 {len(neg)-len(wrong)}/{len(neg)}  漏过(给了组内字) {wrong}")
    gate = [r["id"] for r in neg if gated(Q[r["id"]])]
print(" 质量闸拦下的负例", len(gate))

# 强真值：给字率/准确率（含质量闸）
print("\n[强真值 A+B，4 类模型(全部负例训练)，不同闸]")
for thr in (0.5, 0.8):
    for useq in (False, True):
        out = {}
        for bk in ("vol02", "vol03", "vol04"):
            S = [r for r in R if strong(r) and r["book"] == bk and r["id"] in F]
            gave = ok = 0; errs = []
            for r in S:
                if useq and gated(Q[r["id"]]): continue
                d = decide(m_all.predict_proba(F[r["id"]].reshape(1, -1))[0], thr)
                if d: 
                    gave += 1; ok += d == r["gold"]
                    if d != r["gold"]: errs.append(r["id"])
            out[bk] = f"{len(S)}格 给{gave} 对{ok} 弃{len(S)-gave} 错{errs}"
        print(f" thr{thr} 质量闸{'开' if useq else '关'}:", out)

# 弱标签格（按册留出，含负例训练）：被质量闸/非组内拦下的比例
print("\n[已放行弱标签格，按册留出] 拦下比例（越低越好；拦下的格＝送审增量）")
tot = collections.Counter()
for bk in sorted({r["book"] for r in R if r["core"]}):
    trp = [r for r in pos if r["book"] != bk]
    X = np.vstack([np.array([F[r["id"]] for r in trp]), np.array([F[r["id"]] for r in neg])])
    m = mk(); m.fit(X, [CLS.index(r["char"]) for r in trp] + [3] * len(neg))
    T = [r for r in R if r["core"] and r["book"] == bk and r["admit"] and r["char"] in CLS and r["id"] in F and not strong(r)]
    if not T: continue
    P = m.predict_proba(np.array([F[r["id"]] for r in T]))
    g = sum(gated(Q[r["id"]]) for r in T)
    d5 = [decide(p, 0.5) for p in P]; d8 = [decide(p, 0.8) for p in P]
    dis = sum(1 for r, d in zip(T, d5) if d and d != r["char"])
    print(f" {bk}: {len(T)}格 质量闸拦{g}({g/len(T):.0%}) | thr0.5 弃权{sum(d is None for d in d5)}({sum(d is None for d in d5)/len(T):.0%}) 分歧{dis} | thr0.8 弃权{sum(d is None for d in d8)}({sum(d is None for d in d8)/len(T):.0%})")

print("\n[质量闸对 25 候选 + 待审非组内格]")
cand = {d["id"] for d in json.load(open(DS + "/clf_candidates.json"))}
for r in R:
    if r["id"] in cand or (r["core"] and not r["admit"] and (r["ref"] or "") not in CLS and r["id"] in F):
        q = Q[r["id"]]; p = m_all.predict_proba(F[r["id"]].reshape(1, -1))[0] if r["id"] in F else None
        print(r["id"], "ref", r["ref"], "char", r["char"], "闸" if gated(q) else "-", {k: round(float(v), 2) for k, v in q.items()}, "→", decide(p, 0.5), "其他p=%.2f" % p[3])
