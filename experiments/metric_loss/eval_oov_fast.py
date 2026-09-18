# -*- coding: utf-8 -*-
"""`scripts/eval_oov.py` 的快速版：只为扫 12 档 checkpoint 而写。

## 为什么要另写

生产 `_emb_index` 建索引是**逐字**前向（70,304 字 × 4 字体，每字一次
`self._net(x)`，batch=4）。索引按 checkpoint 指纹缓存，所以生产里只付一次；
但本实验要比十几个 checkpoint，每个都得重建——实测 **6,276s / 档**，
12 档要 21 小时，跑不动。

本脚本只改三件事，**口径与产出与官方脚本一致**（同一个 `cache/oov_bench`、
同一个 `base_charset`、同样的 mean-of-templates 余弦检索）：

1. 渲染结果按「字表 + 字体集」缓存成一个大 npz，**与 checkpoint 无关**
   ——12 档共用一份，只付一次渲染钱；
2. 前向按 4,096 张一批，不是每字一批；
3. 只算 `emb`（主指标）与 `cls`（护栏，类外恒 0），不算 hog。

⚠️ 用它出的数要与官方脚本对得上才算数：`--verify <官方 json>` 会拿
官方结果比一遍，差超过 0.5 个点就报错——2026-09-17 首次对齐通过
（ce_base emb top1 73.2% 两边一致）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BENCH = Path("cache/oov_bench")
RCACHE = Path("experiments/metric_loss/out/cache")


def render_bank(charset: tuple[str, ...], size: int = 64) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """字表 → (所有模板图, 每图所属字的下标, 字名表)。与 checkpoint 无关，可复用。"""
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.synth import render_char
    fonts = _font_files()
    key = hashlib.sha1(("bank|" + "".join(charset) + "|"
                        + "|".join(map(str, fonts))).encode()).hexdigest()[:16]
    f = RCACHE / f"bank_{key}.npz"
    if f.exists():
        z = np.load(f, allow_pickle=False)
        return z["imgs"], z["owner"], z["chars"].tolist()
    imgs, owner, names = [], [], []
    for ch in charset:
        ims = []
        for fp in fonts:
            try:
                im = render_char(ch, fp, size=size)
            except Exception:  # noqa: BLE001
                continue
            if im is not None and im.any():
                ims.append(im.astype(np.uint8))
        if not ims:
            continue
        oi = len(names)
        names.append(ch)
        for im in ims:
            imgs.append(im); owner.append(oi)
    A = np.stack(imgs); O = np.array(owner, np.int32)
    RCACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(f, imgs=A, owner=O, chars=np.array(names))
    return A, O, names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--charset", default="unicode-cjk-ab")
    ap.add_argument("--json", default=None)
    ap.add_argument("--bs", type=int, default=4096)
    ap.add_argument("--verify", default=None, help="官方 eval_oov.py 的 json，对齐校验")
    a = ap.parse_args()

    import cv2
    import torch
    import torch.nn.functional as F
    from open_guji_cv.clustering.charset_spec import base_charset
    from open_guji_cv.clustering.cnn_candidates import _build_net

    items = [json.loads(l) for l in
             (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    Q, G = [], []
    for it in items:
        im = cv2.imread(str(BENCH / it["png"]), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        Q.append((im > 127).astype(np.uint8)); G.append(it["char"])
    src = [it.get("src") or it.get("source") for it in items][:len(G)]
    cs = tuple(base_charset(a.charset))
    print(f"集 {len(G)} 条 / {len(set(G))} 字种；字表 {a.charset} {len(cs)} 字", flush=True)

    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    classes = list(ck["classes"])
    net = _build_net(len(classes), len(ck["comps"]))
    net.load_state_dict(ck["state"])
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = net.to(dev).eval()

    t0 = time.time()
    A, O, names = render_bank(cs)
    print(f"模板 {len(A)} 张 / {len(names)} 字  渲染 {time.time()-t0:.0f}s", flush=True)

    t0 = time.time()
    acc = np.zeros((len(names), 256), np.float64)
    with torch.no_grad():
        for i in range(0, len(A), a.bs):
            xb = torch.tensor(A[i:i + a.bs][:, None].astype(np.float32), device=dev)
            e, _, _ = net(xb)
            e = e.cpu().numpy().astype(np.float64)
            np.add.at(acc, O[i:i + a.bs], e)
    cnt = np.bincount(O, minlength=len(names)).astype(np.float64)[:, None]
    M = acc / np.maximum(cnt, 1)
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    M = M.astype(np.float32)
    print(f"索引 {time.time()-t0:.0f}s", flush=True)

    nidx = {c: i for i, c in enumerate(names)}
    cidx = {c: i for i, c in enumerate(classes)}
    in_cs = np.array([cidx[c] for c in cs if c in cidx], np.int64)
    cs_names = [c for c in cs if c in cidx]

    emb_rank, cls_rank = [], []
    with torch.no_grad():
        for i in range(0, len(Q), 256):
            xb = torch.tensor(np.stack(Q[i:i + 256])[:, None].astype(np.float32), device=dev)
            e, lg, _ = net(xb)
            ev = F.normalize(e, dim=1).cpu().numpy()
            sim = ev @ M.T
            for r in np.argsort(-sim, axis=1)[:, :10]:
                emb_rank.append([names[j] for j in r])
            sub = lg[:, torch.tensor(in_cs, device=dev)]
            for r in sub.topk(min(10, len(cs_names)), dim=1).indices.cpu().numpy():
                cls_rank.append([cs_names[j] for j in r])

    def acc_at(ranks, k):
        return 100.0 * np.mean([G[i] in ranks[i][:k] for i in range(len(G))])

    res = {}
    for nm, rk in (("cls", cls_rank), ("emb", emb_rank)):
        res[nm] = {f"top{k}": acc_at(rk, k) for k in (1, 5, 10)}
    print("\n源         top-1    top-5   top-10")
    for nm in ("cls", "emb"):
        r = res[nm]
        print(f"{nm:8s} {r['top1']:6.1f}% {r['top5']:7.1f}% {r['top10']:7.1f}%")
    for s in sorted({x for x in src if x}):
        m = [i for i in range(len(G)) if src[i] == s]
        if not m:
            continue
        t1 = 100.0 * np.mean([G[i] in emb_rank[i][:1] for i in m])
        t10 = 100.0 * np.mean([G[i] in emb_rank[i][:10] for i in m])
        print(f"  emb / src={s:8s} n={len(m):4d}  top1={t1:5.1f}%  top10={t10:5.1f}%")

    if a.verify:
        off = json.loads(Path(a.verify).read_text(encoding="utf-8"))["result"]
        for nm in ("cls", "emb"):
            for k in ("top1", "top5", "top10"):
                d = abs(res[nm][k] - off[nm][k])
                if d > 0.5:
                    raise SystemExit(f"对齐失败 {nm}.{k}: 本脚本 {res[nm][k]:.2f} "
                                     f"vs 官方 {off[nm][k]:.2f}（差 {d:.2f}）")
        print("\n✅ 与官方 eval_oov.py 对齐（全部指标差 ≤0.5 点）")
    if a.json:
        Path(a.json).write_text(json.dumps(
            {"charset": a.charset, "ckpt": a.ckpt, "n": len(G),
             "n_chars": len(set(G)), "result": res}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print("→", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
