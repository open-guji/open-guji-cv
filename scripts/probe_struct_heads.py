# -*- coding: utf-8 -*-
"""Step A′：冻结现役 CNN 主干，只在它的 256-d embedding 上训结构头 + 槽位部件头（线性探针 / 小 MLP）。

    PYTHONIOENCODING=utf-8 python scripts/probe_struct_heads.py [--ckpt models/glyph_cnn_r5/best.pt]
        [--arch linear|mlp] [--epochs 40] [--font-degrade 1] [--out cache/struct_probe] [--json out.json]

为什么这么做（任务卡 2026-09-22 T1）：r6 把两个头挂在主干上联训，unseen −0.4、oov −2.8、
结构头 90.8——多学的东西在拿类外泛化换类内精度。探针法 embedding 一根毛不动，unseen / oov
定义上不变，验收只剩「结构头 ≥ 95%（oov 合体）+ 槽位 top-3 报数」。若探针到不了 95，
说明 r5 的 embedding 里本来就没有足够的结构信息，那才轮到改主干（T9）。

数据（全部只依赖仓内 + `cache/` 的评测包，云端 CPU 可跑）：
- 训练：glyph_bench `seen_train` 真刻例 + 全部类的字体渲染（`_font_files()`，含 genmin）
  + 每张渲染一份 `train_glyph_cnn.degrade` 退化副本；
- 验证：glyph_bench `seen_test`；
- 报数：oov_bench 314（口径与 `eval_struct_heads.py` 逐位相同：结构头合体/独体分开、
  槽位 top-3 只算词表内标签）、glyph_bench `unseen` / `mid`。
标签全部由 IDS 派生（`ids_struct.struct_index / slot_keys_of / build_slot_labels`），零标注；
类表用 checkpoint 自带的 `classes`（r5 = 4,654），槽位词表 `min_count=3` 与 r6 同口径。

产物：`<out>/probe_<arch>.pt`（`state`、`arch`、`struct_classes`、`slot_labels`、
`vocab_fingerprint`、`backbone`），embedding 缓存 `<out>/emb_<指纹>.npz`。
**不进管线**；接进 `CnnCandidates` 当外挂头是 T2 的事。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BENCH = Path("cache/glyph_bench")
OOV = Path("cache/oov_bench")


def _load_degrade():
    spec = importlib.util.spec_from_file_location("tg", Path(__file__).with_name("train_glyph_cnn.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # 只取 degrade；模块顶层没有副作用（main 在 __main__ 里）
    return mod.degrade


def _png(p: str) -> str:
    return p.replace("\\", "/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--arch", default="linear", choices=["linear", "mlp"])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--font-degrade", type=int, default=1, help="每张字体渲染配几份退化副本")
    ap.add_argument("--no-fonts", action="store_true", help="只用真刻例训（对照）")
    ap.add_argument("--out", default="cache/struct_probe")
    ap.add_argument("--json", default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    import cv2
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates, fingerprint
    from open_guji_cv.clustering.font_candidates import _font_files, font_set_fingerprint
    from open_guji_cv.clustering.ids_struct import (SINGLE, STRUCT_CLASSES, build_slot_labels,
                                                    slot_keys_of, struct_index, structure_of,
                                                    vocab_fingerprint)
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.synth import render_char

    torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    ckpt = Path(a.ckpt) if a.ckpt else DEFAULT_CKPT
    cnn = CnnCandidates(ckpt)
    if not cnn.available:
        print("没有 checkpoint / torch", file=sys.stderr); return 2
    cnn._ensure()
    classes = list(cnn._classes)
    cidx = {c: i for i, c in enumerate(classes)}
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    bb_fp = fingerprint(ckpt)
    print(f"主干 {ckpt} ({bb_fp})  类 {len(classes)}", flush=True)

    # ── 标签 ──
    struct_classes = list(STRUCT_CLASSES)
    slot_labels = build_slot_labels(classes, min_count=3)
    sidx = {k: i for i, k in enumerate(slot_labels)}
    print(f"结构头 {len(struct_classes)} 类；槽位标签 {len(slot_labels)}（词表指纹 {vocab_fingerprint()}）")

    def slot_vec(ch: str) -> np.ndarray:
        v = np.zeros(len(slot_labels), np.float32)
        for k in slot_keys_of(ch):
            if k in sidx:
                v[sidx[k]] = 1.0
        return v

    # ── embedding（缓存）──
    def embed_imgs(imgs: list[np.ndarray]) -> np.ndarray:
        outs = []
        for i in range(0, len(imgs), 256):
            outs.append(cnn.embed(imgs[i:i + 256]))
        return np.concatenate(outs) if outs else np.zeros((0, 256), np.float32)

    items = [json.loads(l) for l in (BENCH / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    oov = [json.loads(l) for l in (OOV / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def real_split(split):
        xs, cs = [], []
        for it in items:
            if it["split"] != split:
                continue
            img = cv2.imread(_png(it["png"]), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            xs.append(normalize_patch(img).astype(np.uint8)); cs.append(it["char"])
        return xs, cs

    cache_key = hashlib.sha1(f"{bb_fp}|{font_set_fingerprint()}|{a.font_degrade}|{a.seed}|v1".encode()).hexdigest()[:12]
    cache = out / f"emb_{cache_key}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        E = {k: z[k] for k in z.files}
        print(f"embedding 缓存命中 {cache}")
    else:
        E = {}
        t0 = time.time()
        for split in ("seen_train", "seen_test", "unseen", "mid"):
            xs, cs = real_split(split)
            E[f"{split}_emb"] = embed_imgs(xs); E[f"{split}_chars"] = np.array(cs)
            print(f"  {split}: {len(xs)} 张  {time.time()-t0:.0f}s", flush=True)
        xs, cs = [], []
        for it in oov:
            im = cv2.imread(str(OOV / _png(it["png"])), cv2.IMREAD_GRAYSCALE)
            if im is not None:
                xs.append((im > 127).astype(np.uint8)); cs.append(it["char"])
        E["oov_emb"] = embed_imgs(xs); E["oov_chars"] = np.array(cs)
        E["oov_src"] = np.array([it["src"] for it in oov][:len(cs)])
        print(f"  oov: {len(xs)} 张  {time.time()-t0:.0f}s", flush=True)
        degrade = _load_degrade()
        fxs, fcs = [], []
        for f in _font_files():
            n = 0
            for ch in classes:
                try:
                    im = render_char(ch, f, size=64)
                except Exception:
                    continue
                if im is None or not im.any():
                    continue
                fxs.append(im.astype(np.uint8)); fcs.append(ch); n += 1
                for _ in range(a.font_degrade):
                    fxs.append(degrade(im.astype(np.uint8), rng)); fcs.append(ch)
            print(f"  字体 {Path(f).name}: {n} 类  {time.time()-t0:.0f}s", flush=True)
        E["font_emb"] = embed_imgs(fxs); E["font_chars"] = np.array(fcs)
        print(f"  字体渲染 {len(fxs)} 张 embedding 完成  {time.time()-t0:.0f}s", flush=True)
        np.savez(cache, **E)

    # ── 组训练集 ──
    def labels_for(chars):
        st = np.array([struct_index(c) for c in chars], np.int64)
        sl = np.stack([slot_vec(c) for c in chars]) if len(chars) else np.zeros((0, len(slot_labels)), np.float32)
        return st, sl

    Xtr = E["seen_train_emb"]; Ctr = list(E["seen_train_chars"])
    if not a.no_fonts:
        Xtr = np.concatenate([Xtr, E["font_emb"]]); Ctr += list(E["font_chars"])
    Str, Ltr = labels_for(Ctr)
    Xte, Cte = E["seen_test_emb"], list(E["seen_test_chars"]); Ste, Lte = labels_for(Cte)
    print(f"训练 {len(Xtr)} 条（真刻例 {len(E['seen_train_emb'])}）/ 验证 {len(Xte)}")

    # ── 头 ──
    d = Xtr.shape[1]
    if a.arch == "linear":
        head = nn.ModuleDict({"struct": nn.Linear(d, len(struct_classes)), "slot": nn.Linear(d, len(slot_labels))})
        def fwd(x): return head["struct"](x), head["slot"](x)
    else:
        trunk = nn.Sequential(nn.Linear(d, a.hidden), nn.ReLU(), nn.Dropout(0.2))
        head = nn.ModuleDict({"trunk": trunk, "struct": nn.Linear(a.hidden, len(struct_classes)),
                              "slot": nn.Linear(a.hidden, len(slot_labels))})
        def fwd(x):
            h = head["trunk"](x); return head["struct"](h), head["slot"](h)
    opt = torch.optim.AdamW(head.parameters(), lr=a.lr, weight_decay=1e-4)
    # 结构类别极不均衡（⿰ ⿱ 占大头）：CE 用 1/sqrt(freq) 权，免得少数结构被吞
    cnt = np.bincount(Str, minlength=len(struct_classes)).astype(np.float64)
    w = torch.tensor((1.0 / np.sqrt(np.maximum(cnt, 1))) / (1.0 / np.sqrt(np.maximum(cnt, 1))).mean(), dtype=torch.float32)
    SCALE = 16.0   # 主干出的是单位向量；r6 的头见到的是 ×16 的 cos-logit 尺度，探针也照这个喂
    Xtr_t = torch.tensor(Xtr * SCALE); Str_t = torch.tensor(Str); Ltr_t = torch.tensor(Ltr)
    Xte_t = torch.tensor(Xte * SCALE)

    def eval_struct(X, S):
        head.eval()
        with torch.no_grad():
            st, _ = fwd(torch.tensor(X * SCALE))
        head.train()
        return float((st.argmax(1).numpy() == S).mean()) if len(S) else float("nan")

    n = len(Xtr_t); bs = 512
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)
    for ep in range(a.epochs):
        perm = torch.randperm(n); tl = 0.0
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            st, sl = fwd(Xtr_t[idx])
            loss = F.cross_entropy(st, Str_t[idx], weight=w) + F.binary_cross_entropy_with_logits(sl, Ltr_t[idx])
            opt.zero_grad(); loss.backward(); opt.step(); tl += float(loss) * len(idx)
        sched.step()
        if ep % 5 == 4 or ep == a.epochs - 1:
            print(f"ep {ep+1:3d} loss {tl/n:.4f}  seen_test struct {eval_struct(Xte, Ste):.3f}", flush=True)

    # ── 报数（与 eval_struct_heads.py 同口径）──
    head.eval()
    labels = set(slot_labels)

    def report(name, X, chars, src=None):
        with torch.no_grad():
            st, sl = fwd(torch.tensor(X * SCALE))
        sp = torch.softmax(st, 1).numpy(); lp = torch.sigmoid(sl).numpy()
        ok = n_ = ok1 = n1 = hit = tot = 0
        per_src: dict = {}
        for j, g in enumerate(chars):
            s = structure_of(g)
            pred = struct_classes[int(sp[j].argmax())]
            if s.top == SINGLE:
                n1 += 1; ok1 += int(pred == SINGLE)
            else:
                n_ += 1; ok += int(pred == s.top)
                if src is not None:
                    ps = per_src.setdefault(str(src[j]), [0, 0]); ps[0] += int(pred == s.top); ps[1] += 1
            top3 = set(np.argsort(-lp[j])[:3].tolist())
            for key in slot_keys_of(g):
                if key in labels:
                    tot += 1; hit += int(sidx[key] in top3)
        row = {"n_compound": n_, "struct_acc_compound": 100.0 * ok / max(n_, 1),
               "n_single": n1, "struct_acc_single": 100.0 * ok1 / max(n1, 1),
               "slot_top3": 100.0 * hit / max(tot, 1), "slot_labels_counted": tot}
        if per_src:
            row["by_src"] = {k: 100.0 * v[0] / max(v[1], 1) for k, v in per_src.items()}
        print(f"{name:10s} 结构头 合体 {row['struct_acc_compound']:5.1f}% (n={n_})  独体 {row['struct_acc_single']:5.1f}% (n={n1})"
              f"  槽位 top-3 {row['slot_top3']:5.1f}% (标签 {tot})" + (f"  按源 {row['by_src']}" if per_src else ""))
        return row

    res = {"ckpt": str(ckpt), "backbone": bb_fp, "arch": a.arch, "epochs": a.epochs, "fonts": not a.no_fonts,
           "n_train": int(len(Xtr)), "slot_labels": len(slot_labels)}
    res["oov"] = report("oov_bench", E["oov_emb"], list(E["oov_chars"]), list(E["oov_src"]))
    res["seen_test"] = report("seen_test", Xte, Cte)
    res["unseen"] = report("unseen", E["unseen_emb"], list(E["unseen_chars"]))
    res["mid"] = report("mid", E["mid_emb"], list(E["mid_chars"]))
    torch.save({"state": head.state_dict(), "arch": a.arch, "hidden": a.hidden, "scale": SCALE,
                "struct_classes": struct_classes, "slot_labels": slot_labels,
                "vocab_fingerprint": vocab_fingerprint(), "backbone": bb_fp}, out / f"probe_{a.arch}.pt")
    print(f"→ {out / f'probe_{a.arch}.pt'}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
