"""入人八字形分类器离线评测。训练只用弱标签（C 档，放行字＝整理本＝证人），不含任何强真值格、不含 vol04；
强真值（A+B）只用来评：给字率 / 给字准确率 / 弃权率，按册报。"""
import sys, json, collections, warnings
import numpy as np
from feat import *
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
warnings.filterwarnings("ignore")

R = [r for r in load_items() if r["split"] != "extra"]
F = {}
for r in R:
    f = features(crop_path(r))
    if f is not None:
        F[r["id"]] = f[0]
print("有特征的格", len(F), "/", len(R))

def strong(r): return r["gold_tier"] in ("A_human", "B_vision") and r["gold"] in CLS
def weak(r): return r["gold_tier"] == "C_weak" and r["char"] in CLS
TRAIN_BOOKS = {"vol02", "vol03", "vol05", "vol06", "vol07", "vol08", "vol09", "vol10"}
tr = [r for r in R if weak(r) and r["id"] in F and r["book"] in TRAIN_BOOKS]
Xtr = np.array([F[r["id"]] for r in tr]); ytr = np.array([CLS.index(r["char"]) for r in tr])
print("训练(弱标签)", len(tr), collections.Counter(r["char"] for r in tr))

models = {
 "logreg": make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000, class_weight="balanced")),
 "rf": RandomForestClassifier(300, min_samples_leaf=2, class_weight="balanced", random_state=0, n_jobs=-1),
}
for k, m in models.items(): m.fit(Xtr, ytr)

def report(name, m, thr):
    print(f"\n== {name}  弃权阈值 p<{thr}")
    for bk in ("vol02", "vol03", "vol04"):
        S = [r for r in R if strong(r) and r["book"] == bk and r["id"] in F]
        if not S: continue
        P = m.predict_proba(np.array([F[r["id"]] for r in S]))
        gave = ok = 0; errs = []
        for r, p in zip(S, P):
            if p.max() >= thr:
                gave += 1
                if CLS[p.argmax()] == r["gold"]: ok += 1
                else: errs.append((r["id"], r["gold"], CLS[p.argmax()], round(float(p.max()), 2)))
        print(f"{bk}: 强真值{len(S)} 给字{gave}({gave/len(S):.0%}) 准确{ok}/{gave} 弃权{len(S)-gave}({(len(S)-gave)/len(S):.0%}) 错{errs}")

if __name__ == "__main__":
    for name, m in models.items():
        for thr in (0.5, 0.8, 0.95):
            report(name, m, thr)
