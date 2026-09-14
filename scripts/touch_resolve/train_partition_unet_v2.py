# -*- coding: utf-8 -*-
"""档 3 地板 v2：类别无关归属网络。v1 的教训（在真实金标窗口上输出横向条带、识别掉到 41%）：
小网络感受野盖不住一个字，学到的是绝对行位置先验。v2 改四处：
  1. 更深（5 级，到 1/16 分辨率）+ 底层空洞卷积，感受野覆盖整个双格窗口；
  2. 输入加一个归一化行坐标通道，位置信息显式给，不靠 padding 学；
  3. 增广：随机纵向偏移 0–40px、随机纵向缩放 0.85–1.05、轻微水平偏移——切断「第 N 行必是 A」的捷径；
  4. vol01 + vol02 两份合成对（4 万）全预载内存，16 轮。

    python scripts/touch_resolve/train_partition_unet_v2.py --train --data D:/data/touch_synth/vol01,D:/data/touch_synth/vol02 --epochs 16
    python scripts/touch_resolve/train_partition_unet_v2.py --eval-gold
评测复用 v1 的 eval_gold（同尺子），只换模型与输入。
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np

CANVAS_H, CANVAS_W = 288, 192
MODEL_DIR = Path("D:/data/touch_synth/models")


def to_canvas(gray: np.ndarray, owner: np.ndarray | None = None, top: int = 0):
    h, w = gray.shape
    s = min(1.0, (CANVAS_H - top) / h, CANVAS_W / w)
    if s < 1.0:
        gray = cv2.resize(gray, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        if owner is not None:
            owner = cv2.resize(owner, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)
    img = np.full((CANVAS_H, CANVAS_W), 255, np.uint8)
    img[top: top + gray.shape[0], : gray.shape[1]] = gray
    own = None
    if owner is not None:
        own = np.zeros((CANVAS_H, CANVAS_W), np.uint8)
        own[top: top + owner.shape[0], : owner.shape[1]] = owner
    return img, own, s


def make_input(img: np.ndarray):
    import torch
    ink = (255 - img).astype(np.float32) / 255.0
    yy = np.linspace(0, 1, CANVAS_H, dtype=np.float32)[:, None].repeat(CANVAS_W, axis=1)
    return torch.from_numpy(np.stack([ink, yy], 0))


def build_model():
    import torch
    import torch.nn as nn

    def block(i, o, dil=1):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=dil, dilation=dil), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=dil, dilation=dil), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class UNet(nn.Module):
        def __init__(self, ch=(24, 48, 96, 160, 256), n_cls=3):
            super().__init__()
            self.e1 = block(2, ch[0]); self.e2 = block(ch[0], ch[1]); self.e3 = block(ch[1], ch[2])
            self.e4 = block(ch[2], ch[3]); self.e5 = block(ch[3], ch[4], dil=2)
            self.pool = nn.MaxPool2d(2)
            self.u4 = nn.ConvTranspose2d(ch[4], ch[3], 2, stride=2); self.d4 = block(ch[3] * 2, ch[3])
            self.u3 = nn.ConvTranspose2d(ch[3], ch[2], 2, stride=2); self.d3 = block(ch[2] * 2, ch[2])
            self.u2 = nn.ConvTranspose2d(ch[2], ch[1], 2, stride=2); self.d2 = block(ch[1] * 2, ch[1])
            self.u1 = nn.ConvTranspose2d(ch[1], ch[0], 2, stride=2); self.d1 = block(ch[0] * 2, ch[0])
            self.out = nn.Conv2d(ch[0], n_cls, 1)

        def forward(self, x):
            e1 = self.e1(x); e2 = self.e2(self.pool(e1)); e3 = self.e3(self.pool(e2))
            e4 = self.e4(self.pool(e3)); e5 = self.e5(self.pool(e4))
            d4 = self.d4(torch.cat([self.u4(e5), e4], 1)); d3 = self.d3(torch.cat([self.u3(d4), e3], 1))
            d2 = self.d2(torch.cat([self.u2(d3), e2], 1)); d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
            return self.out(d1)

    return UNet()


class MemDS:
    """全预载：原尺寸灰度 + owner 存内存，取样时增广再贴画布。"""

    def __init__(self, roots: list[Path], metas: list[tuple[Path, dict]], augment: bool):
        self.items = []
        for root, m in metas:
            g = cv2.imread(str(root / "pairs" / f"{m['i']:06d}.png"), 0)
            o = cv2.imread(str(root / "pairs" / f"{m['i']:06d}_own.png"), 0)
            if g is not None and o is not None:
                self.items.append((g, o))
        self.augment = augment

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        import torch
        g, o = self.items[i]
        top = 0
        if self.augment:
            sy = random.uniform(0.85, 1.05); sx = random.uniform(0.95, 1.03)
            if abs(sy - 1) > 0.01 or abs(sx - 1) > 0.01:
                g = cv2.resize(g, (max(8, int(g.shape[1] * sx)), max(8, int(g.shape[0] * sy))), interpolation=cv2.INTER_AREA)
                o = cv2.resize(o, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
            dx = random.randint(0, 8)
            g = np.pad(g, ((0, 0), (dx, 0)), constant_values=255); o = np.pad(o, ((0, 0), (dx, 0)), constant_values=0)
            top = random.randint(0, 40)
        img, own, _ = to_canvas(g, o, top=top)
        y = torch.from_numpy(own.astype(np.int64)); y[y == 3] = -1
        return make_input(img), y


def train(a) -> Path:
    import torch
    import torch.nn.functional as F
    roots = [Path(p) for p in a.data.split(",")]
    metas = []
    for root in roots:
        for l in (root / "meta.jsonl").read_text(encoding="utf-8").splitlines():
            metas.append((root, json.loads(l)))
    random.Random(0).shuffle(metas)
    n_val = max(300, len(metas) // 25)
    val, tr = metas[:n_val], metas[n_val:]
    t0 = time.time()
    dtr, dva = MemDS(roots, tr, True), MemDS(roots, val, False)
    print(f"预载 {len(dtr)} + {len(dva)} 对 {time.time() - t0:.0f}s", flush=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    dl = torch.utils.data.DataLoader(dtr, batch_size=a.bs, shuffle=True, num_workers=0, drop_last=True)
    dlv = torch.utils.data.DataLoader(dva, batch_size=32, shuffle=False, num_workers=0)
    steps = a.epochs * len(dl)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=steps)
    cw = torch.tensor([0.2, 1.0, 1.0], device=dev)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    ck = MODEL_DIR / "partition_unet_v2.pt"
    best = 1e9
    print(f"train {len(dtr)} / val {len(dva)} device={dev} steps={steps}", flush=True)
    for ep in range(a.epochs):
        net.train(); tot = 0.0; n = 0
        for x, y in dl:
            x, y = x.to(dev), y.to(dev)
            loss = F.cross_entropy(net(x), y, weight=cw, ignore_index=-1)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += float(loss) * x.size(0); n += x.size(0)
        net.eval(); vt = 0.0; vn = 0; err_px = []; blob60 = []
        with torch.no_grad():
            for x, y in dlv:
                x, y = x.to(dev), y.to(dev)
                lg = net(x)
                vt += float(F.cross_entropy(lg, y, weight=cw, ignore_index=-1)) * x.size(0); vn += x.size(0)
                pred = lg.argmax(1); m = (y > 0)
                e = ((pred != y) & m)
                err_px += e.flatten(1).sum(1).float().tolist()
                for k in range(e.size(0)):
                    em = e[k].cpu().numpy().astype(np.uint8)
                    if em.any():
                        _, _, st, _ = cv2.connectedComponentsWithStats(em, connectivity=8)
                        blob60.append(int(st[1:, cv2.CC_STAT_AREA].max() >= 60))
                    else:
                        blob60.append(0)
        vloss = vt / vn
        print(f"ep {ep + 1}/{a.epochs} train {tot / n:.4f} val {vloss:.4f} val_err_px mean {np.mean(err_px):.1f} median {np.median(err_px):.0f} blob>=60 {np.mean(blob60):.1%}  {time.time() - t0:.0f}s", flush=True)
        if vloss < best:
            best = vloss
            torch.save({"state": net.state_dict(), "canvas": (CANVAS_H, CANVAS_W), "v": 2}, ck)
    print(f"→ {ck}", flush=True)
    return ck


def eval_gold(a) -> None:
    import torch
    from common import (INK_TH, Loader, OUT_ROOT, Recognizer, half_patch, jdump, normalize, seam_chosen, seam_gold, window)
    from exp3_partition_eval import err_stats
    from templates import owner_from_seam
    ck = Path(a.ckpt) if a.ckpt else MODEL_DIR / "partition_unet_v2.pt"
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model().to(dev); net.load_state_dict(torch.load(ck, map_location=dev)["state"]); net.eval()
    L = Loader(); R = Recognizer()
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    out = OUT_ROOT / f"unet_{ck.stem}"; (out / "viz").mkdir(parents=True, exist_ok=True)
    per = []; norms = []; keys = []; cases = []
    for it in L.gold_items(books=a.books.split(",")):
        c, _ = L.resolve(it)
        if c is not None and L.image_of(c) is not None:
            cases.append(c)
    for ci, case in enumerate(cases):
        img = L.image_of(case); win, y0, _ = window(case, img)
        W = (win < INK_TH).astype(np.uint8)
        cimg, _, s = to_canvas(win, top=8)
        x = make_input(cimg)[None].to(dev)
        with torch.no_grad():
            pred = net(x).argmax(1)[0].cpu().numpy().astype(np.uint8)
        pred = pred[8:]
        h, w = win.shape
        if s < 1.0:
            ph, pw = int(h * s), int(w * s)
            pred = cv2.resize(pred[:ph, :pw], (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            pred = pred[:h, :w]
        raw_owner = np.where(W > 0, np.where(pred == 0, 2, pred), 0).astype(np.uint8)
        # 连通体多数票平滑（与 templates.Registrar.partition 同精神）
        owner = raw_owner.copy()
        n_cc, lab = cv2.connectedComponents(W, connectivity=8)
        for i in range(1, n_cc):
            m = lab == i; v = raw_owner[m]; nA, nB = int((v == 1).sum()), int((v == 2).sum())
            if nA >= 0.85 * (nA + nB):
                owner[m] = 1
            elif nB >= 0.85 * (nA + nB):
                owner[m] = 2
        og = owner_from_seam(W, seam_gold(case) - y0); oc = owner_from_seam(W, seam_chosen(case) - y0)
        rec = {"id": case.id, "verdict": case.verdict, "book": case.book, "poly": bool(case.gold_poly), "has_chars": case.has_chars(), "err": {}}
        for k, o in (("unet", owner), ("unet_raw", raw_owner), ("chosen", oc)):
            n, blob = err_stats(o, og); rec["err"][k] = {"px": n, "blob": blob}
        if case.id in exp1:
            e1 = exp1[case.id]; rk = e1["rank"]["gold"]
            rec["label_ok"] = bool(rk["fused_above"] and rk["fused_above"] <= 5 and rk["fused_below"] and rk["fused_below"] <= 5)
            rec["recog_chosen"] = {"above": e1["rank"]["chosen"]["fused_above"], "below": e1["rank"]["chosen"]["fused_below"]}
            for side, val in (("above", 1), ("below", 2)):
                hp = half_patch(win, owner == val)
                if hp is not None:
                    norms.append(normalize(hp)); keys.append((ci, side))
        per.append((rec, win, owner))
    from open_guji_cv.clustering.cnn_candidates import rrf
    cls_all, emb_all = [], []
    for i in range(0, len(norms), 256):
        cls_all += R.cls_topk(norms[i:i + 256], k=5); emb_all += R.emb_topk(norms[i:i + 256], k=5)
    for (ci, side), cl, em in zip(keys, cls_all, emb_all):
        c = cases[ci]; truth = c.char_above if side == "above" else c.char_below
        fused = rrf([x for x, _ in cl], [x for x, _ in em], k=5)
        per[ci][0].setdefault("recog_unet", {})[side] = (1 + fused.index(truth)) if truth in fused else None
    rows = [r for r, _, _ in per]

    def agg(rs, k):
        px = np.array([r["err"][k]["px"] for r in rs]); bl = np.array([r["err"][k]["blob"] for r in rs])
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)), "px_p90": float(np.percentile(px, 90)),
                "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4)} if px.size else None

    def recog_both(rs, k):
        v = [int(r[k]["above"] == 1 and r[k]["below"] == 1) for r in rs if k in r and "above" in r[k] and "below" in r[k]]
        return (round(float(np.mean(v)), 4), len(v)) if v else None

    strata = {"all": rows, "poly": [r for r in rows if r["poly"]], "label_ok": [r for r in rows if r.get("label_ok")],
              "label_ok+poly": [r for r in rows if r.get("label_ok") and r["poly"]]}
    for v in ("seam_ok", "ok", "overlap", "moved"):
        strata[f"label_ok/{v}"] = [r for r in rows if r.get("label_ok") and r["verdict"] == v]
    summary = {"ckpt": str(ck), "n": len(rows),
               "err": {s: {k: agg(rs, k) for k in ("unet", "unet_raw", "chosen")} for s, rs in strata.items()},
               "recog_both_top1": {s: {"unet": recog_both(rs, "recog_unet"), "chosen": recog_both(rs, "recog_chosen")} for s, rs in strata.items()}}
    jdump(rows, out / "per_case.json"); jdump(summary, out / "summary.json")
    print(json.dumps(summary["err"]["label_ok+poly"], ensure_ascii=False)); print(summary["recog_both_top1"]["label_ok"])
    worst = sorted([p for p in per if p[0].get("label_ok")], key=lambda p: -p[0]["err"]["unet"]["px"])[:24]
    for rec, win, owner in worst:
        vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR); ov = vis.copy(); ov[owner == 1] = (0, 0, 220); ov[owner == 2] = (220, 90, 0)
        sheet = np.concatenate([vis, cv2.addWeighted(vis, 0.35, ov, 0.65, 0)], axis=1)
        cv2.imwrite(str(out / "viz" / (rec["id"].replace(":", "_") + ".png")), cv2.resize(sheet, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    print(f"→ {out}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true"); ap.add_argument("--eval-gold", action="store_true")
    ap.add_argument("--data", default="D:/data/touch_synth/vol01,D:/data/touch_synth/vol02")
    ap.add_argument("--epochs", type=int, default=16); ap.add_argument("--bs", type=int, default=24); ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--ckpt", default=None); ap.add_argument("--books", default="vol01,vol02,vol03")
    a = ap.parse_args()
    if a.train:
        train(a)
    if a.eval_gold:
        eval_gold(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
