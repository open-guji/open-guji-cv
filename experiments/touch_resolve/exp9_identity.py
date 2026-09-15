# -*- coding: utf-8 -*-
"""实验九：用识别器给候选池做「身份打分」——切完两半各自认得出期望字吗。

    python experiments/touch_resolve/exp9_identity.py [--cc-max 400]

实验七/八：U-Net 一致率、模板贴合度、两者合议都停在大块错 ~1.5%（10 条）。残余的是「游离顶/底部件」双向歧义：
書的底日该归誰，只有知道上字是書才分得开。实验一说三种缝对识别几乎无影响，那是**平均**；这里只问：
在这 10 条这种「一整块部件换边」的候选之间，识别器分不分得开。
对每条金标的每个池成员（几何候选 + U-Net 归属）：按归属切两半 → 现役 CNN（分类头 + embedding 检索，RRF 融合）
→ 期望字（金标 char_above/char_below）在融合榜的名次 rank_a / rank_b。
规则：
  I1  身份优先：both_top1 > rank 和更小 > agree_w（实验七 S1）
  I2  身份只做否决：先按 S1 选；若 S1 选中者某一侧 rank>1，而池里有成员两侧都 top-1 → 换成它（多个则 agree_w 高者）
  I3  I2 + 「选中者与 U-Net 分歧最大块 ≥150 且 U-Net 成员两侧 top-1」→ 换 U-Net
产出 out/exp9/per_case.json（逐成员 rank / agree_w / err）、summary.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Loader, OUT_ROOT, Recognizer, half_patch, jdump, normalize, seam_chosen, seam_gold, seams_candidates, window  # noqa: E402
from exp3_partition_eval import err_stats  # noqa: E402
from exp6_selector import unet_owner  # noqa: E402
from exp7_select_pool import dis_blob  # noqa: E402
from templates import owner_from_seam  # noqa: E402
from train_partition_unet_v2 import MODEL_DIR, build_model  # noqa: E402


def main() -> int:
    import torch
    from open_guji_cv.clustering.cnn_candidates import rrf
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc-max", type=int, default=400)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model().to(dev)
    net.load_state_dict(torch.load(MODEL_DIR / "partition_unet_v2.pt", map_location=dev)["state"])
    net.eval()
    L = Loader()
    R = Recognizer()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    out = OUT_ROOT / "exp9"
    out.mkdir(parents=True, exist_ok=True)
    per = []
    norms = []
    keys = []          # (case_idx, member_idx, side)
    for it in L.gold_items(books=a.books.split(","), need_chars=True):
        if it.id not in frame_ok:
            continue
        c, _ = L.resolve(it)
        if c is None or L.image_of(c) is None:
            continue
        rk = (exp1.get(c.id) or {}).get("rank", {}).get("gold", {})
        label_ok = bool(rk.get("fused_above") and rk["fused_above"] <= 5 and rk.get("fused_below") and rk["fused_below"] <= 5)
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        W, ou, conf = unet_owner(net, dev, win, a.cc_max)
        ink = W > 0
        cw = conf[ink]
        og = owner_from_seam(W, seam_gold(c) - y0)
        sc = seam_chosen(c)
        members = []
        seen = []
        owners = []
        for kind, seam in seams_candidates(c):
            key = tuple(int(v) for v in seam)
            if key in seen:
                continue
            seen.append(key)
            o = owner_from_seam(W, seam - y0)
            n, blob = err_stats(o, og)
            eq = (o[ink] == ou[ink])
            members.append({"kind": kind, "is_chosen": bool(np.array_equal(seam, sc)), "err": {"px": n, "blob": blob},
                            "agree_w": round(float((cw * eq).sum() / max(cw.sum(), 1e-6)), 4) if eq.size else 1.0,
                            "dis_unet": dis_blob(o, ou, W)})
            owners.append(o)
        if not any(m["is_chosen"] for m in members):
            oc = owner_from_seam(W, sc - y0)
            n, blob = err_stats(oc, og)
            eq = (oc[ink] == ou[ink])
            members.append({"kind": "chosen", "is_chosen": True, "err": {"px": n, "blob": blob},
                            "agree_w": round(float((cw * eq).sum() / max(cw.sum(), 1e-6)), 4), "dis_unet": dis_blob(oc, ou, W)})
            owners.append(oc)
        n_u, blob_u = err_stats(ou, og)
        members.append({"kind": "unet", "is_chosen": False, "err": {"px": n_u, "blob": blob_u}, "agree_w": 1.0, "dis_unet": 0})
        owners.append(ou)
        ci = len(per)
        for mi, o in enumerate(owners):
            for side, val in (("a", 1), ("b", 2)):
                hp = half_patch(win, o == val)
                if hp is None:
                    continue
                norms.append(normalize(hp))
                keys.append((ci, mi, side))
        per.append({"id": c.id, "verdict": c.verdict, "book": c.book, "page": c.page, "label_ok": label_ok,
                    "char_above": c.char_above, "char_below": c.char_below, "members": members})
    print(f"用例 {len(per)}，半字图 {len(norms)}", flush=True)
    cls_all, emb_all = [], []
    for i in range(0, len(norms), 256):
        cls_all += R.cls_topk(norms[i:i + 256], k=10)
        emb_all += R.emb_topk(norms[i:i + 256], k=10)
    for (ci, mi, side), cl, em in zip(keys, cls_all, emb_all):
        r = per[ci]
        truth = r["char_above"] if side == "a" else r["char_below"]
        fused = rrf([x for x, _ in cl], [x for x, _ in em], k=10)
        m = r["members"][mi]
        m[f"rank_{side}"] = (1 + fused.index(truth)) if truth in fused else None
        m[f"cls_{side}"] = round(float(next((s for x, s in cl if x == truth), 0.0)), 4)
    for r in per:
        for m in r["members"]:
            ra, rb = m.get("rank_a") or 11, m.get("rank_b") or 11
            m["id_sum"] = ra + rb
            m["both1"] = bool(ra == 1 and rb == 1)
    jdump(per, out / "per_case.json")

    def agg(errs):
        px = np.array([e["px"] for e in errs]); bl = np.array([e["blob"] for e in errs])
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4),
                "blob_ge150": round(float((bl >= 150).mean()), 4)}

    def fmt(x):
        return f"{x['px_mean']:7.1f} {x['px_median']:6.0f} {x['le20px']:7.1%} {x['blob_ge60']:8.1%} {x['blob_ge150']:8.1%}"

    def geo(r):
        return [m for m in r["members"] if m["kind"] != "unet"]

    def chosen(r):
        return next(m for m in r["members"] if m["is_chosen"])

    def unet(r):
        return next(m for m in r["members"] if m["kind"] == "unet")

    def s1(r):
        return max(geo(r), key=lambda m: (m["agree_w"], m["is_chosen"]))

    def I1(r):
        return max(geo(r), key=lambda m: (m["both1"], -m["id_sum"], m["agree_w"], m["is_chosen"]))

    def I1u(r):
        return max(r["members"], key=lambda m: (m["both1"], -m["id_sum"], m["agree_w"], m["is_chosen"]))

    def I2(r):
        b = s1(r)
        if b["both1"]:
            return b
        alt = [m for m in geo(r) if m["both1"]]
        return max(alt, key=lambda m: m["agree_w"]) if alt else b

    def I3(r):
        b = I2(r)
        u = unet(r)
        if b["dis_unet"] >= 150 and u["both1"] and not b["both1"]:
            return u
        return b

    def I4(r):
        """身份差距版：S1 选中者 id_sum 比池内最优大 ≥2 才换（几何候选内）。"""
        b = s1(r)
        best = min(geo(r), key=lambda m: (m["id_sum"], -m["agree_w"]))
        return best if b["id_sum"] - best["id_sum"] >= 2 else b

    def oracle_geo(r):
        return min(geo(r), key=lambda m: (m["err"]["blob"], m["err"]["px"]))

    def oracle(r):
        return min(r["members"], key=lambda m: (m["err"]["blob"], m["err"]["px"]))

    methods = {"chosen": chosen, "unet": unet, "S1 agree_w": s1, "I1 身份优先(几何)": I1, "I1u 身份优先(含unet)": I1u,
               "I2 身份否决": I2, "I3 I2+U-Net否决": I3, "I4 身份差距≥2": I4, "候选池上限": oracle_geo, "全池上限": oracle}
    rows = [r for r in per if r["label_ok"]]
    summary = {"n": len(rows), "label_ok": {}, "by_verdict": {}}
    print(f"{'method':24s} px_mean median  le20px  blob>=60 blob>=150")
    for name, f in methods.items():
        x = agg([f(r)["err"] for r in rows])
        summary["label_ok"][name] = x
        print(f"{name:24s} {fmt(x)}")
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        summary["by_verdict"][v] = {name: agg([f(r)["err"] for r in rr]) for name, f in methods.items()}
        print(f"-- {v} n={len(rr)} blob>=150: " + "  ".join(f"{m}={summary['by_verdict'][v][m]['blob_ge150']:.1%}" for m in ("chosen", "S1 agree_w", "I2 身份否决", "I3 I2+U-Net否决", "I4 身份差距≥2", "全池上限")))
    # 身份信号在「整块换边」候选对上分不分得开：S1 残余大块错的条目，对的成员 vs 错的成员的 id_sum
    res = [r for r in rows if s1(r)["err"]["blob"] >= 150]
    print(f"S1 残余大块错 {len(res)} 条的成员 (kind, blob, rank_a, rank_b, agree_w)：")
    for r in res:
        print("  ", r["id"], r["char_above"] + r["char_below"], [(m["kind"][:4], m["err"]["blob"], m.get("rank_a"), m.get("rank_b"), m["agree_w"]) for m in r["members"]])
    jdump(summary, out / "summary.json")
    print(f"→ {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
