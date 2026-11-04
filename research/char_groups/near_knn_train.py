"""形近护栏格书级刻形近邻（`groups.near_knn`）：收刻例、按册留出、导出 `config/groups/near_knn.json`。

    python research/char_groups/near_knn_train.py collect <产物根> <原图根> feats.npz [--mirror-x]
    python research/char_groups/near_knn_train.py train feats.npz near_knn.json [--skip-chars 己已巳] [--skip-groups dt,wyu]

- collect：`<产物根>/<册>/seed_admit|cell_shrink` 与 `<原图根>/<册>/<页>.png`；刻例＝已放行格（不含 human、book_knn
  通道），全书 ≥ `--min-total` 格的字，每字每册 ≤ `--per-vol`、全书 ≤ `--per-char`；待审格也收（只为报数）。
  字块按 cell_shrink bbox_page 裁（`--mirror-x`：原图左右镜像存的，x 取 w-1-x）。
- train：PCA 60；按册留出——每册的刻例用其余各册判，候选＝{本字, 待审里与它成对出现过的字}，报 放／错；
  `guard`＝留出判对格全库 5 近邻距离 99.5 分位。门槛缺省 k=7、票 7、比 <0.6、全库票 ≥4
  （全唐文 r8：留出 24,704 格错 4，看图 4 格都是原放行标错、近邻判对；比 <0.7 时错 12，含 犬→大 几→凡 兔→冤 舟→丹 真错）。
"""
import argparse
import glob
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from open_guji_cv.groups import near_knn, rr_shape  # noqa: E402

PCA_K = 60


def _walk_align(o, out):
    if isinstance(o, dict):
        if "id" in o and "align_char" in o:
            out[o["id"]] = o["align_char"]
        for y in o.values():
            _walk_align(y, out)
    elif isinstance(o, list):
        for y in o:
            _walk_align(y, out)


def collect(a):
    from PIL import Image
    files = sorted(glob.glob(f"{a.products}/*/seed_admit/p*.json"))
    random.seed(11)
    random.shuffle(files)
    tot = Counter()
    for f in files:
        for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
            for x in col["chars"]:
                if x["admit"] and x.get("char"):
                    tot[x["char"]] += 1
    cnt, cv, F, M = Counter(), Counter(), [], []
    for f in files:
        v = f.split(os.sep)[-3]
        pg = int(os.path.basename(f)[1:5])
        img = Path(a.images) / v / f"{pg}.png"
        if not img.exists():
            continue
        want = []
        for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
            for x in col["chars"]:
                ch = x.get("char")
                if not x["admit"]:
                    want.append((x, "q"))
                elif (ch and tot[ch] >= a.min_total and cnt[ch] < a.per_char and cv[(v, ch)] < a.per_vol
                      and x.get("channel") not in ("book_knn", "near_knn", "human") and x.get("provenance") != "human"):
                    cnt[ch] += 1
                    cv[(v, ch)] += 1
                    want.append((x, "b"))
        if not want:
            continue
        amap = {}
        _walk_align(json.load(open(f"{a.products}/{v}/align_ref/p{pg:04d}.json", encoding="utf-8")), amap)
        cs = json.load(open(f"{a.products}/{v}/cell_shrink/p{pg:04d}.json", encoding="utf-8"))["char_index"]
        bb = {y["id"]: y["bbox_page"] for cc in cs["columns"] for y in cc["chars"]}
        im = np.array(Image.open(img).convert("L"))
        w = im.shape[1]
        for x, kind in want:
            b = bb.get(x["id"])
            if not b:
                continue
            x0, y0, x1, y1 = (int(t) for t in b)
            if a.mirror_x:
                x0, x1 = w - 1 - x1, w - 1 - x0
            ft = rr_shape.features(im[y0:y1, x0:x1])[0]
            if ft is None:
                continue
            F.append(ft.astype(np.float16))
            M.append({"id": x["id"], "vol": v, "char": x.get("char"), "kind": kind, "ref": amap.get(x["id"])})
    np.savez_compressed(a.out, f=np.array(F), meta=np.array(json.dumps(M, ensure_ascii=False)))
    print("收", len(M), Counter(m["kind"] for m in M), "字", len(cnt))


def train(a):
    z = np.load(a.feats)
    X = z["f"].astype(np.float32)
    M = json.loads(str(z["meta"]))
    kind = np.array([m["kind"] for m in M])
    B = np.where(kind == "b")[0]
    mu = X[B].mean(0)
    _, _, vt = np.linalg.svd(X[B][::2] - mu, full_matrices=False)
    P = vt[:PCA_K]
    lab = np.array([M[i]["char"] for i in B])
    vol = np.array([M[i]["vol"] for i in B])
    base = {"schema": near_knn.SCHEMA, "k": a.k, "votes_min": a.votes_min, "ratio_max": a.ratio_max,
            "full_votes_min": a.full_votes_min, "min_n": a.min_n, "guard": 1e9,
            "skip_chars": sorted(set(a.skip_chars)), "skip_groups": sorted(filter(None, a.skip_groups.split(",")))}
    model = {**base, "pca_mean": mu, "pca": P, "bank": (X[B] - mu) @ P.T, "labels": lab}
    model["_by"] = {c: np.where(lab == c)[0] for c in set(lab.tolist())}
    # 待审里成对出现的字（本格字／整理本）→ 留出用的候选对
    pairs = Counter()
    for m in M:
        if m["kind"] == "q" and m["char"] and m["ref"] and m["char"] != m["ref"]:
            pairs[tuple(sorted((m["char"], m["ref"])))] += 1
    rng = np.random.default_rng(2)
    res = []
    for (c1, c2) in pairs:
        for ch, oth in ((c1, c2), (c2, c1)):
            js = model["_by"].get(ch)
            if js is None:
                continue
            for j in rng.choice(js, min(len(js), a.hold_per_char), replace=False):
                v = near_knn.judge_feat(X[B[j]], {**model, "guard": 1e9}, [ch, oth], exclude=(vol == vol[j]))
                if "pick" in v:
                    res.append((M[B[j]]["id"], ch, v))
    ok = [r for r in res if r[2]["char"] is not None]
    err = [r for r in ok if r[2]["char"] != r[1]]
    guard = float(np.percentile([r[2]["nn"] for r in ok if r[2]["char"] == r[1]], 99.5))
    msg = f"按册留出 {len(res)} 格（{len(pairs)} 对）：放 {len(ok)} 错 {len(err)}；guard={guard:.3f}"
    print(msg)
    for i, y, v in err:
        print("  错", i, "标", y, "判", v["char"], v["votes"], v["ratio"], v["full"], v["full_votes"])
    out = {**base, "guard": guard, "note": f"刻例 {len(B)} 格 {len(model['_by'])} 字；{msg}",
           "pca_mean": near_knn.pack(mu), "pca": near_knn.pack(P), "bank": near_knn.pack(model["bank"]),
           "labels": lab.tolist()}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("写", a.out, f"{Path(a.out).stat().st_size / 1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collect")
    c.add_argument("products"); c.add_argument("images"); c.add_argument("out")
    c.add_argument("--mirror-x", action="store_true")
    c.add_argument("--min-total", type=int, default=5)
    c.add_argument("--per-char", type=int, default=40)
    c.add_argument("--per-vol", type=int, default=6)
    t = sp.add_parser("train")
    t.add_argument("feats"); t.add_argument("out")
    t.add_argument("--k", type=int, default=7)
    t.add_argument("--votes-min", type=int, default=7)
    t.add_argument("--ratio-max", type=float, default=0.6)
    t.add_argument("--full-votes-min", type=int, default=4)
    t.add_argument("--min-n", type=int, default=5)
    t.add_argument("--hold-per-char", type=int, default=25)
    t.add_argument("--skip-chars", default="己已巳")
    t.add_argument("--skip-groups", default="jys,dt,wyu,liang,hou")
    a = ap.parse_args()
    collect(a) if a.cmd == "collect" else train(a)


if __name__ == "__main__":
    main()
