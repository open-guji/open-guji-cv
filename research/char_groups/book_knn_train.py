"""字组书级刻形近邻判法训练与按册留出（`groups.book_knn`）→ `config/groups/book_knn/<组>.json`。

    python research/char_groups/book_knn_train.py <组 id> <cells.json> <字块目录> <输出.json> [--exclude id,id]

- `cells.json`：[{id, vol, admit, char, ref}]，已放行且 char 是组员的格当刻例（放行字当标签，方法论 2.7）；
  `ref` 是整理本对位字（align_ref 的 align_char，B 档要用）；看图确认放错的格用 --exclude 去掉。
- 字块目录：`<id 把 : 换成 _>.png` 灰度字块（原图按 cell_shrink bbox_page 裁，或管线 char_patch）。
- 刻例少于 `--min-n` 格的字不进库（近邻投票拿不到票），那些字的格自然弃权。
- 按册留出：每册用其余各册建的库判，A、B 两档分别报 对／错，弃权另计；`guard` 取留出里判对格的 nn 99.5 分位。
  门槛缺省 k=7、A 票≥6 距离比<0.8、B 票≥5 距离比<1.0（全唐文门族：A 留出 1,957 对 1 错）。
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from open_guji_cv.groups import book_knn, rr_shape  # noqa: E402
from open_guji_cv.groups.registry import FLOW_GROUPS  # noqa: E402

PCA_K = 60


def build(F, lab, tr, a):
    m = F[tr].mean(0)
    _, _, vt = np.linalg.svd(F[tr] - m, full_matrices=False)
    P = vt[:PCA_K]
    return {"schema": book_knn.SCHEMA, "group": a.group, "pca_mean": m, "pca": P, "bank": (F[tr] - m) @ P.T,
            "labels": lab[tr], "k": a.k, "votes_min": a.votes_min, "ratio_max": a.ratio_max,
            "ref_votes_min": a.ref_votes_min, "ref_ratio_max": a.ref_ratio_max, "guard": 1e9}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group"); ap.add_argument("cells"); ap.add_argument("patches"); ap.add_argument("out")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--k", type=int, default=7)
    ap.add_argument("--votes-min", type=int, default=6)
    ap.add_argument("--ratio-max", type=float, default=0.8)
    ap.add_argument("--ref-votes-min", type=int, default=5)
    ap.add_argument("--ref-ratio-max", type=float, default=1.0)
    a = ap.parse_args()
    import cv2
    members = FLOW_GROUPS[a.group].members
    ex = set(filter(None, a.exclude.split(",")))
    cells = [c for c in json.load(open(a.cells, encoding="utf-8"))
             if c["admit"] and c["char"] in members and c["id"] not in ex]
    n = Counter(c["char"] for c in cells)
    cells = [c for c in cells if n[c["char"]] >= a.min_n]
    F, keep = [], []
    for c in cells:
        g = cv2.imread(str(Path(a.patches) / (c["id"].replace(":", "_") + ".png")), cv2.IMREAD_GRAYSCALE)
        f = rr_shape.features(g)[0] if g is not None else None
        if f is not None:
            F.append(f); keep.append(c)
    F = np.array(F, np.float32)
    lab = np.array([c["char"] for c in keep]); vol = np.array([c["vol"] for c in keep])
    res = []
    for v in sorted(set(vol)):
        te = np.where(vol == v)[0]; tr = np.where(vol != v)[0]
        m = build(F, lab, tr, a)
        for i in te:
            res.append((keep[i]["id"], lab[i], book_knn.judge_feat(F[i], m, keep[i].get("ref"))))
    guard = float(np.percentile([r["nn"] for _, y, r in res if r["char"] == y], 99.5))
    st = Counter()
    for i, y, r in res:
        if r["char"] is None or r["nn"] > guard:
            st["弃"] += 1
        else:
            st[(r["tier"], "对" if r["char"] == y else "错")] += 1
            if r["char"] != y:
                print("  错", i, "标", y, "判", r["char"], r["tier"], r["votes"], r["ratio"])
    msg = (f"按册留出 {len(res)} 格：A 对{st[('A', '对')]} 错{st[('A', '错')]}；B 对{st[('B', '对')]} 错{st[('B', '错')]}；"
           f"弃{st['弃']}（guard={guard:.3f}）")
    print(msg)
    m = build(F, lab, np.arange(len(F)), a)
    m.update(guard=guard, note=f"{a.group} 刻例 {len(F)}（{dict(Counter(lab.tolist()))}）；{msg}")
    m = {k: (v.round(4).tolist() if isinstance(v, np.ndarray) and v.dtype.kind == "f" else
             v.tolist() if isinstance(v, np.ndarray) else v) for k, v in m.items()}
    Path(a.out).write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("写", a.out, f"{Path(a.out).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
