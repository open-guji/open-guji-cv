"""日/曰 宽高比分析（R2）。读 extract.py 产出的 samples.jsonl，出图 + 错分率表。

阈值与逻辑回归一律在训练折上定（按 (vol,page) 分组 5 折），报测试折错分率；
错分率分类报（日→曰、曰→日）并给平衡错分率（两类各自错分率的均值），
因为 曰 ≈ 5× 日，总体准确率会被多数类抬高。
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

import numpy as np

OUT = sys.argv[1]
FIG = sys.argv[2]
os.makedirs(FIG, exist_ok=True)
R = [json.loads(l) for l in open(os.path.join(OUT, "samples.jsonl"), encoding="utf-8")]
R = [r for r in R if r["nb_n"] >= 2 and r["nb_w_mean"] and r["admit"] or r["tier"] == "unadmitted"]


def feats(r):
    rw = r["w"] / r["nb_w_mean"] if r["nb_w_mean"] else np.nan
    rh = r["h"] / r["nb_h_mean"] if r["nb_h_mean"] else np.nan
    return dict(
        raw=r["w"] / r["h"],                       # 紧墨框宽/高
        rel=rw / rh if rh else np.nan,             # 同列邻字归一后的宽高比
        w_p=r["w"] / r["period"],                  # 宽/字距
        h_p=r["h"] / r["period"],
        rw=rw, rh=rh,
        dens=r.get("ink_density") or np.nan,
        hbar=1.0 if r.get("hbar_right") else 0.0,
    )


for r in R:
    r["f"] = feats(r)
y_of = lambda r: 1 if r["label"] == "曰" else 0     # 曰=1


def best_thr(x, y):
    """平衡错分率最小的单阈值（曰 在阈值之上）。"""
    xs = np.sort(np.unique(x))
    cand = (xs[1:] + xs[:-1]) / 2
    best = (9, None)
    n1, n0 = max(1, (y == 1).sum()), max(1, (y == 0).sum())
    for t in cand:
        e1 = ((x <= t) & (y == 1)).sum() / n1
        e0 = ((x > t) & (y == 0)).sum() / n0
        b = (e0 + e1) / 2
        if b < best[0]:
            best = (b, t)
    return best[1]


def cv_threshold(rows, key, train_pool, k=5, seed=0):
    """按页分组 k 折：阈值在训练折（train_pool 里的行）上定，在测试折上出预测。返回 {id:(pred)}"""
    pages = sorted({(r["vol"], r["page"]) for r in rows})
    rng = np.random.RandomState(seed)
    rng.shuffle(pages)
    fold = {p: i % k for i, p in enumerate(pages)}
    pred = {}
    for f in range(k):
        tr = [r for r in train_pool if fold[(r["vol"], r["page"])] != f and not np.isnan(r["f"][key])]
        x = np.array([r["f"][key] for r in tr])
        y = np.array([y_of(r) for r in tr])
        t = best_thr(x, y)
        for r in rows:
            if fold[(r["vol"], r["page"])] == f:
                v = r["f"][key]
                pred[r["id"] + str(r["sub"])] = None if np.isnan(v) else int(v > t)
    return pred


def rate(rows, pred):
    rows = [r for r in rows if pred.get(r["id"] + str(r["sub"])) is not None]
    n1 = [r for r in rows if r["label"] == "曰"]
    n0 = [r for r in rows if r["label"] == "日"]
    e1 = sum(pred[r["id"] + str(r["sub"])] == 0 for r in n1)   # 曰→日
    e0 = sum(pred[r["id"] + str(r["sub"])] == 1 for r in n0)   # 日→曰
    bal = ((e1 / len(n1) if n1 else 0) + (e0 / len(n0) if n0 else 0)) / 2 if (n1 and n0) else float("nan")
    tot = (e0 + e1) / max(1, len(rows))
    return dict(n日=len(n0), n曰=len(n1), 日误成曰=e0, 曰误成日=e1, 总错=tot, 平衡错=bal)


adm = [r for r in R if r["tier"] != "unadmitted"]
pool = [r for r in adm if r["tier"] in ("human", "tri", "dual")]   # 训练只用较可信的标签
subsets = {
    "人裁": [r for r in adm if r["tier"] == "human"],
    "三路一致": [r for r in adm if r["tier"] == "tri"],
    "二路一致(缺5-b)": [r for r in adm if r["tier"] == "dual"],
    "其他放行(参考)": [r for r in adm if r["tier"] == "other"],
    "可信合集(人裁+三路+二路)": pool,
    "全部放行": adm,
}
res = {}
for key in ["raw", "rel", "w_p"]:
    pred = cv_threshold(adm, key, pool)
    res[key] = {n: rate(s, pred) for n, s in subsets.items()}
    # 分正文/列尾
    for kd in ("body", "tail"):
        res[key]["可信合集·" + kd] = rate([r for r in pool if r["kind"] == kd], pred)
    for v in sorted({r["vol"] for r in pool}):
        res[key]["可信合集·" + v] = rate([r for r in pool if r["vol"] == v], pred)

# 全量阈值（仅作展示/落规则，不用于错分率）
thr = {}
for key in ["raw", "rel", "w_p"]:
    x = np.array([r["f"][key] for r in pool if not np.isnan(r["f"][key])])
    y = np.array([y_of(r) for r in pool if not np.isnan(r["f"][key])])
    thr[key] = float(best_thr(x, y))

# 逻辑回归（2–3 特征），同样按页分组 CV
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

def cv_lr(cols, k=5, seed=0):
    pages = sorted({(r["vol"], r["page"]) for r in adm})
    rng = np.random.RandomState(seed)
    rng.shuffle(pages)
    fold = {p: i % k for i, p in enumerate(pages)}
    ok = lambda r: not any(np.isnan(r["f"][c]) for c in cols)
    pred = {}
    for f in range(k):
        tr = [r for r in pool if fold[(r["vol"], r["page"])] != f and ok(r)]
        X = np.array([[r["f"][c] for c in cols] for r in tr])
        y = np.array([y_of(r) for r in tr])
        sc = StandardScaler().fit(X)
        m = LogisticRegression(class_weight="balanced", C=1.0, max_iter=1000).fit(sc.transform(X), y)
        for r in adm:
            if fold[(r["vol"], r["page"])] == f and ok(r):
                pred[r["id"] + str(r["sub"])] = int(m.predict(sc.transform([[r["f"][c] for c in cols]]))[0])
    return pred

lrs = {}
for name, cols in {"LR[rel,dens]": ["rel", "dens"], "LR[rel,dens,hbar]": ["rel", "dens", "hbar"],
                   "LR[raw,w_p,dens]": ["raw", "w_p", "dens"]}.items():
    pred = cv_lr(cols)
    lrs[name] = {n: rate(s, pred) for n, s in subsets.items()}

# 现行管线对照：人裁格上，管线自己（库首位 / 5-b 首位）判对多少
hum = subsets["人裁"]
cur = defaultdict(lambda: defaultdict(int))
for r in hum:
    for nm, v in (("库首位", r["lib_top"]), ("5-b首位", r["rare_top"]), ("整理本字", r["ref"])):
        cur[nm]["对" if v == r["label"] else ("空" if not v else ("同对字但判反" if v in "日曰" else "他字"))] += 1
cur = {k: dict(v) for k, v in cur.items()}

json.dump(dict(thr=thr, cv=res, lr=lrs, current_on_human=cur, n=len(adm)),
          open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- 图 ----
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
fig, axs = plt.subplots(2, 3, figsize=(16, 8))
for ax, key, ttl in zip(axs[0], ["raw", "rel", "w_p"], ["紧墨框 w/h", "相对宽高比 (w/邻均w)/(h/邻均h)", "宽/字距"]):
    for lab, col in (("日", "tab:red"), ("曰", "tab:blue")):
        v = [r["f"][key] for r in pool if r["label"] == lab and not np.isnan(r["f"][key])]
        ax.hist(v, bins=40, alpha=0.55, color=col, label=f"{lab} n={len(v)}", density=True)
    ax.axvline(thr[key], color="k", ls="--")
    ax.set_title(ttl + "（可信合集）")
    ax.legend()
for lab, col in (("日", "tab:red"), ("曰", "tab:blue")):
    s = [r for r in adm if r["label"] == lab]
    axs[1][0].scatter([r["f"]["w_p"] for r in s], [r["f"]["h_p"] for r in s], s=6, alpha=0.4, c=col, label=lab)
axs[1][0].set_xlabel("w/period"); axs[1][0].set_ylabel("h/period"); axs[1][0].legend(); axs[1][0].set_title("宽-高散点（全部放行）")
for lab, col in (("日", "tab:red"), ("曰", "tab:blue")):
    s = [r for r in subsets["人裁"] if r["label"] == lab]
    axs[1][1].scatter([r["f"]["raw"] for r in s], [r["f"]["rel"] for r in s], s=30, c=col, label=lab)
axs[1][1].set_xlabel("raw w/h"); axs[1][1].set_ylabel("rel"); axs[1][1].legend(); axs[1][1].set_title("人裁格")
for lab, col in (("日", "tab:red"), ("曰", "tab:blue")):
    v = [r["f"]["raw"] for r in adm if r["label"] == lab and r["tier"] == "other"]
    axs[1][2].hist(v, bins=30, alpha=0.55, color=col, label=f"{lab} n={len(v)}", density=True)
axs[1][2].axvline(thr["raw"], color="k", ls="--"); axs[1][2].legend(); axs[1][2].set_title("其他放行格(参考) w/h")
plt.tight_layout()
plt.savefig(os.path.join(FIG, "ri_yue_dist.png"), dpi=110)
print(json.dumps(dict(thr=thr), ensure_ascii=False))
for key in res:
    print("==", key)
    for n, v in res[key].items():
        print(f"  {n:28s} {v}")
for k, t in lrs.items():
    print("==", k)
    for n in ("人裁", "三路一致", "可信合集(人裁+三路+二路)", "其他放行(参考)"):
        print(f"  {n:28s} {t[n]}")
print("current_on_human", cur)
