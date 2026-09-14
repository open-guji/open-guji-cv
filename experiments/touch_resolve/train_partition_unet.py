# -*- coding: utf-8 -*-
"""档 3 地板：类别无关的逐像素归属网络（小 U-Net），只用合成粘连对训练，零人工标注、不看字是什么。

    python experiments/touch_resolve/train_partition_unet.py --train --data D:/data/touch_synth/vol01 --epochs 8
    python experiments/touch_resolve/train_partition_unet.py --eval-gold [--ckpt ...]

输入：灰度双格窗口（贴到 256×192 白底画布左上角）；输出：每像素 3 类（背景 / 上字 A / 下字 B）。
合成真值里的「两者都有墨」(3) 像素不算损失（ignore）。评测在 touching-cuts 金标上，尺子同实验三
（err_px / err_blob 相对人工金标缝；归属后两半识别 top-1）。
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
PRIOR_SIGMA = 6.0        # 第二通道：Step3 直线格线位置的高斯带（部署时现成有；v1 没有它就去学绝对行号，真窗口一变就错）
AUG_DY, AUG_DX = 48, 12
MODEL_DIR = Path("D:/data/touch_synth/models")


def to_canvas(gray: np.ndarray, owner: np.ndarray | None = None):
    """窗口 → 固定画布（左上对齐；超出就等比缩小）。返回 (img, own, scale)。"""
    h, w = gray.shape
    s = min(1.0, CANVAS_H / h, CANVAS_W / w)
    if s < 1.0:
        gray = cv2.resize(gray, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        if owner is not None:
            owner = cv2.resize(owner, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)
    img = np.full((CANVAS_H, CANVAS_W), 255, np.uint8)
    img[: gray.shape[0], : gray.shape[1]] = gray
    own = None
    if owner is not None:
        own = np.zeros((CANVAS_H, CANVAS_W), np.uint8)
        own[: owner.shape[0], : owner.shape[1]] = owner
    return img, own, s


def prior_channel(y_line: float, h: int = CANVAS_H, w: int = CANVAS_W, sigma: float = PRIOR_SIGMA) -> np.ndarray:
    rows = np.arange(h, dtype=np.float32)
    band = np.exp(-((rows - float(y_line)) / sigma) ** 2)
    return np.repeat(band[:, None], w, axis=1)


def build_model(in_ch: int = 2):
    import torch
    import torch.nn as nn

    def block(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class UNet(nn.Module):
        def __init__(self, ch=(16, 32, 64, 128), n_cls=3):
            super().__init__()
            self.e1 = block(in_ch, ch[0]); self.e2 = block(ch[0], ch[1]); self.e3 = block(ch[1], ch[2]); self.e4 = block(ch[2], ch[3])
            self.pool = nn.MaxPool2d(2)
            self.u3 = nn.ConvTranspose2d(ch[3], ch[2], 2, stride=2); self.d3 = block(ch[2] * 2, ch[2])
            self.u2 = nn.ConvTranspose2d(ch[2], ch[1], 2, stride=2); self.d2 = block(ch[1] * 2, ch[1])
            self.u1 = nn.ConvTranspose2d(ch[1], ch[0], 2, stride=2); self.d1 = block(ch[0] * 2, ch[0])
            self.out = nn.Conv2d(ch[0], n_cls, 1)

        def forward(self, x):
            e1 = self.e1(x); e2 = self.e2(self.pool(e1)); e3 = self.e3(self.pool(e2)); e4 = self.e4(self.pool(e3))
            d3 = self.d3(torch.cat([self.u3(e4), e3], 1)); d2 = self.d2(torch.cat([self.u2(d3), e2], 1))
            d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
            return self.out(d1)

    return UNet()


class SynthDS:
    """metas 里每条带 `_root`（可多套书混合）。返回 2 通道：墨 + 直线先验带。"""

    def __init__(self, metas: list[dict], augment: bool):
        self.metas = metas; self.augment = augment

    def __len__(self):
        return len(self.metas)

    def __getitem__(self, i):
        import torch
        m = self.metas[i]; root = Path(m["_root"])
        g = cv2.imread(str(root / "pairs" / f"{m['i']:06d}.png"), 0)
        o = cv2.imread(str(root / "pairs" / f"{m['i']:06d}_own.png"), 0)
        y_line = float(m["straight_best_y"] or g.shape[0] // 2)
        if self.augment:
            dy = random.randint(0, AUG_DY); dx = random.randint(0, AUG_DX)
            g = np.pad(g, ((dy, 0), (dx, 0)), constant_values=255); o = np.pad(o, ((dy, 0), (dx, 0)), constant_values=0)
            y_line += dy
            s = random.uniform(0.85, 1.1)
            if s != 1.0:
                g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                o = cv2.resize(o, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
                y_line *= s
            y_line += random.gauss(0, 8)            # 模拟 DP 直线格线的误差（金标实测 p90 ≈ 6px，留余量）
        img, own, sc = to_canvas(g, o)
        x = np.stack([(255 - img).astype(np.float32) / 255.0, prior_channel(y_line * sc)], axis=0)
        y = torch.from_numpy(own.astype(np.int64))
        y[y == 3] = -1                      # ignore 重叠像素
        return torch.from_numpy(x), y


def train(a) -> Path:
    import torch
    import torch.nn.functional as F
    roots = [Path(d) for d in a.data.split(",")]
    metas = []
    for root in roots:
        for l in (root / "meta.jsonl").read_text(encoding="utf-8").splitlines():
            m = json.loads(l); m["_root"] = str(root); metas.append(m)
    random.Random(0).shuffle(metas)
    n_val = max(200, len(metas) // 20)
    val, tr = metas[:n_val], metas[n_val:]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    dl = torch.utils.data.DataLoader(SynthDS(tr, True), batch_size=a.bs, shuffle=True, num_workers=0, drop_last=True)
    dlv = torch.utils.data.DataLoader(SynthDS(val, False), batch_size=64, shuffle=False, num_workers=0)
    steps = a.epochs * len(dl)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=steps)
    cw = torch.tensor([0.2, 1.0, 1.0], device=dev)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    ck = MODEL_DIR / f"partition_unetP_{'+'.join(r.name for r in roots)}.pt"   # P = 带直线先验通道；与同目录另一会话的 train_partition_unet_v2.py（partition_unet_v2.pt）区分
    best = 1e9
    t0 = time.time()
    print(f"train {len(tr)} / val {len(val)}  device={dev}  steps={steps}")
    for ep in range(a.epochs):
        net.train(); tot = 0.0; n = 0
        for x, y in dl:
            x, y = x.to(dev), y.to(dev)
            loss = F.cross_entropy(net(x), y, weight=cw, ignore_index=-1)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += float(loss) * x.size(0); n += x.size(0)
        net.eval(); vt = 0.0; vn = 0; err_px = []
        with torch.no_grad():
            for x, y in dlv:
                x, y = x.to(dev), y.to(dev)
                lg = net(x)
                vt += float(F.cross_entropy(lg, y, weight=cw, ignore_index=-1)) * x.size(0); vn += x.size(0)
                pred = lg.argmax(1)
                m = (y > 0)
                err_px += ((pred != y) & m).flatten(1).sum(1).float().tolist()
        vloss = vt / vn
        print(f"ep {ep + 1}/{a.epochs} train {tot / n:.4f} val {vloss:.4f} val_err_px mean {np.mean(err_px):.1f} median {np.median(err_px):.0f}  {time.time() - t0:.0f}s", flush=True)
        if vloss < best:
            best = vloss
            torch.save({"state": net.state_dict(), "canvas": (CANVAS_H, CANVAS_W), "in_ch": 2}, ck)
    print(f"→ {ck}")
    return ck


def eval_gold(a) -> None:
    import torch
    from common import (INK_TH, Loader, OUT_ROOT, Recognizer, half_patch, jdump, normalize, seam_chosen, seam_gold,
                        window)
    from exp3_partition_eval import err_stats
    from templates import owner_from_seam
    ck = Path(a.ckpt) if a.ckpt else MODEL_DIR / f"partition_unetP_{'+'.join(Path(d).name for d in a.data.split(','))}.pt"
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model().to(dev); net.load_state_dict(torch.load(ck, map_location=dev)["state"]); net.eval()
    L = Loader(); R = Recognizer()
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    out = OUT_ROOT / f"unet_{ck.stem}"; (out / "viz").mkdir(parents=True, exist_ok=True)
    per = []; norms = []; keys = []
    cases = []
    for it in L.gold_items(books=a.books.split(",")):
        c, _ = L.resolve(it)
        if c is not None and L.image_of(c) is not None:
            cases.append(c)
    if a.limit:
        cases = cases[: a.limit]
    for ci, case in enumerate(cases):
        img = L.image_of(case); win, y0, _ = window(case, img)
        W = (win < INK_TH).astype(np.uint8)
        cimg, _, s = to_canvas(win)
        x2 = np.stack([(255 - cimg).astype(np.float32) / 255.0, prior_channel((case.straight_y - y0) * s)], axis=0)
        x = torch.from_numpy(x2)[None].to(dev)
        with torch.no_grad():
            pred = net(x).argmax(1)[0].cpu().numpy().astype(np.uint8)
        h, w = win.shape
        if s < 1.0:
            ph, pw = int(h * s), int(w * s)
            pred = cv2.resize(pred[:ph, :pw], (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            pred = pred[:h, :w]
        owner = np.where(W > 0, np.where(pred == 0, 2, pred), 0).astype(np.uint8)   # 墨像素上预测成背景的归下字（少见）
        og = owner_from_seam(W, seam_gold(case) - y0)
        oc = owner_from_seam(W, seam_chosen(case) - y0)
        rec = {"id": case.id, "verdict": case.verdict, "book": case.book, "poly": bool(case.gold_poly),
               "has_chars": case.has_chars(), "err": {}}
        for k, o in (("unet", owner), ("chosen", oc)):
            n, blob = err_stats(o, og); rec["err"][k] = {"px": n, "blob": blob}
        if a.limit:
            print(case.id, "pred hist on ink", np.bincount(owner[W > 0], minlength=3).tolist(), "err", rec["err"], flush=True)
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
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                "px_p90": float(np.percentile(px, 90)), "le20px": round(float((px <= 20).mean()), 4),
                "blob_ge60": round(float((bl >= 60).mean()), 4)} if px.size else None

    def recog_both(rs, k):
        v = [int(r[k]["above"] == 1 and r[k]["below"] == 1) for r in rs if k in r and "above" in r[k] and "below" in r[k]]
        return (round(float(np.mean(v)), 4), len(v)) if v else None

    strata = {"all": rows, "poly": [r for r in rows if r["poly"]],
              "label_ok": [r for r in rows if r.get("label_ok")], "label_ok+poly": [r for r in rows if r.get("label_ok") and r["poly"]]}
    for v in ("seam_ok", "ok", "overlap", "moved"):
        strata[f"label_ok/{v}"] = [r for r in rows if r.get("label_ok") and r["verdict"] == v]
    summary = {"ckpt": str(ck), "n": len(rows),
               "err": {s: {k: agg(rs, k) for k in ("unet", "chosen")} for s, rs in strata.items()},
               "recog_both_top1": {s: {"unet": recog_both(rs, "recog_unet"), "chosen": recog_both(rs, "recog_chosen")} for s, rs in strata.items()}}
    jdump([r for r in rows], out / "per_case.json"); jdump(summary, out / "summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    worst = sorted([p for p in per if p[0].get("label_ok")], key=lambda p: -p[0]["err"]["unet"]["px"])[:24]
    for rec, win, owner in worst:
        vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR); ov = vis.copy(); ov[owner == 1] = (0, 0, 220); ov[owner == 2] = (220, 90, 0)
        sheet = np.concatenate([vis, cv2.addWeighted(vis, 0.35, ov, 0.65, 0)], axis=1)
        cv2.imwrite(str(out / "viz" / (rec["id"].replace(":", "_") + ".png")), cv2.resize(sheet, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    print(f"→ {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true"); ap.add_argument("--eval-gold", action="store_true")
    ap.add_argument("--data", default="D:/data/touch_synth/vol01")
    ap.add_argument("--epochs", type=int, default=8); ap.add_argument("--bs", type=int, default=32); ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--ckpt", default=None); ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.train:
        train(a)
    if a.eval_gold:
        eval_gold(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
