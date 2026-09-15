# -*- coding: utf-8 -*-
"""U-Net v3：**身份条件**归属网络——把上下两字的字体字形当两个输入通道喂给网络。

    python experiments/touch_resolve/train_partition_unet_v3.py --train [--epochs 6] [--lr 1e-3]
    python experiments/touch_resolve/train_partition_unet_v3.py --eval-gold [--cc-max 400]

为什么（2026-09-14 实验七～九 + 真金标微调）：类别无关的 v2 和一切裁判都停在大块错 ~1.3–1.5%，残余全是
「游离顶/底部件归谁」——書的底日、學的子、其的八。这类歧义只有知道**字是什么**才分得开；而 CNN 识别器对整块部件换边
不敏感（实验九）、模板配准又贵又没增益（实验三/四）。所以换个做法：不去「认」，直接把期望字（生产里来自整理本对齐）
的字体字形作为参考图给归属网络，让它学会「照着这个形状分」。这就是「先认后切」的网络版。
输入 4 通道：[墨, 归一化行坐标, 上字字形（贴在画布顶部）, 下字字形（贴在画布底部）]。
训练：从 v2 权重起（首层新增两通道零初始化），合成对（meta 里有 A/B 的 label），15% 样本随机抹掉字形通道
（让它没有身份时也能工作 = 退化成 v2）。评测：金标 frame_ok，字形取金标 char_above/char_below；
另报「字形通道置零」的消融，以及以 v3 当裁判的 S1。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_partition_unet_v2 import CANVAS_H, CANVAS_W, MODEL_DIR, make_input, to_canvas  # noqa: E402

G_H, G_W, G_PAD = 112, 160, 4


class GlyphBank:
    def __init__(self):
        from common import FontTemplates
        self.ft = FontTemplates()
        self.cache: dict[str, np.ndarray | None] = {}

    def get_raw(self, ch: str | None) -> np.ndarray | None:
        """字形紧裁二值（uint8 0/1，原始比例），对齐模式用；渲染不出返回 None。"""
        if not ch or len(ch) != 1:
            return None
        key = "raw:" + ch
        if key not in self.cache:
            got = self.ft.render(ch)
            out = None
            if got is not None:
                b = got[1]
                ys, xs = np.nonzero(b)
                if ys.size:
                    out = b[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].astype(np.uint8)
            self.cache[key] = out
        return self.cache[key]

    def get(self, ch: str | None) -> np.ndarray | None:
        """字形 → (G_H, G_W) float32 0/1，居中等比；渲染不出返回 None。"""
        if not ch or len(ch) != 1:
            return None
        if ch in self.cache:
            return self.cache[ch]
        got = self.ft.render(ch)
        out = None
        if got is not None:
            b = got[1]
            ys, xs = np.nonzero(b)
            if ys.size:
                b = b[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]
                s = min((G_H - 2 * G_PAD) / b.shape[0], (G_W - 2 * G_PAD) / b.shape[1])
                r = cv2.resize(b.astype(np.uint8), (max(1, int(b.shape[1] * s)), max(1, int(b.shape[0] * s))), interpolation=cv2.INTER_AREA)
                out = np.zeros((G_H, G_W), np.float32)
                y0 = (G_H - r.shape[0]) // 2
                x0 = (G_W - r.shape[1]) // 2
                out[y0: y0 + r.shape[0], x0: x0 + r.shape[1]] = (r > 0).astype(np.float32)
        self.cache[ch] = out
        return out


def glyph_channels(up: np.ndarray | None, dn: np.ndarray | None) -> np.ndarray:
    ch = np.zeros((2, CANVAS_H, CANVAS_W), np.float32)
    x0 = (CANVAS_W - G_W) // 2
    if up is not None:
        ch[0, G_PAD: G_PAD + G_H, x0: x0 + G_W] = up
    if dn is not None:
        ch[1, CANVAS_H - G_PAD - G_H: CANVAS_H - G_PAD, x0: x0 + G_W] = dn
    return ch


def make_input_v3(img: np.ndarray, up: np.ndarray | None, dn: np.ndarray | None):
    import torch
    base = make_input(img)                        # (2, H, W)
    g = torch.from_numpy(glyph_channels(up, dn))
    return torch.cat([base, g], 0)


def bbox_of(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if not ys.size:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def jitter_box(box, rng: random.Random, fy=0.25, fx=0.05):
    """训练时抖动框的边：真实评测时框来自直线切点两侧的墨，会比真字范围少/多一截。"""
    if box is None:
        return None
    x0, y0, x1, y1 = box
    h, w = y1 - y0, x1 - x0
    y0 += int(rng.uniform(-fy, fy) * h)
    y1 += int(rng.uniform(-fy, fy) * h)
    x0 += int(rng.uniform(-fx, fx) * w)
    x1 += int(rng.uniform(-fx, fx) * w)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(CANVAS_W, max(x0 + 4, x1)), min(CANVAS_H, max(y0 + 4, y1))
    return [x0, y0, x1, y1]


def glyph_channels_aligned(up_raw, dn_raw, box_a, box_b) -> np.ndarray:
    """对齐模式：把字形拉伸贴进各自的字框（画布坐标 [x0, y0, x1, y1]）。"""
    ch = np.zeros((2, CANVAS_H, CANVAS_W), np.float32)
    for k, (g, box) in enumerate(((up_raw, box_a), (dn_raw, box_b))):
        if g is None or box is None:
            continue
        x0, y0, x1, y1 = box
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        r = cv2.resize(g, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
        ch[k, y0:y1, x0:x1] = (r > 0).astype(np.float32)
    return ch


def make_input_v3a(img: np.ndarray, up_raw, dn_raw, box_a, box_b):
    import torch
    base = make_input(img)
    g = torch.from_numpy(glyph_channels_aligned(up_raw, dn_raw, box_a, box_b))
    return torch.cat([base, g], 0)


def eval_boxes(win: np.ndarray, cut: int, s: float, top: int):
    """评测时的字框：直线切点上/下两侧的墨外接框（窗口坐标）→ 画布坐标。"""
    from common import INK_TH
    W = win < INK_TH
    h = win.shape[0]
    cut = int(min(max(cut, 1), h - 1))
    out = []
    for idx, m in enumerate((W[:cut], W[cut:])):
        b = bbox_of(m)
        if b is None:
            out.append(None)
            continue
        x0, y0, x1, y1 = b
        if idx == 1:
            y0 += cut
            y1 += cut
        out.append([int(x0 * s), int(y0 * s) + top, int(x1 * s), int(y1 * s) + top])
    return out[0], out[1]


def build_model_v3():
    import torch
    import torch.nn as nn

    def block(i, o, dil=1):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=dil, dilation=dil), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=dil, dilation=dil), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class UNet(nn.Module):
        def __init__(self, ch=(24, 48, 96, 160, 256), n_cls=3, in_ch=4):
            super().__init__()
            self.e1 = block(in_ch, ch[0]); self.e2 = block(ch[0], ch[1]); self.e3 = block(ch[1], ch[2])
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


def init_from_v2(net, dev):
    import torch
    sd = torch.load(MODEL_DIR / "partition_unet_v2.pt", map_location=dev)["state"]
    own = net.state_dict()
    for k, v in sd.items():
        if k == "e1.0.weight":
            w = torch.zeros_like(own[k])
            w[:, :2] = v
            own[k] = w
        elif k in own and own[k].shape == v.shape:
            own[k] = v
    net.load_state_dict(own)


def owner_v3(net, dev, win: np.ndarray, up, dn, cc_max: int | None, align_cut: int | None = None):
    """同 exp6.unet_owner：墨像素取上/下两类谁大，连通体多数票只对 ≤cc_max 生效。
    `align_cut` 给了（窗口坐标的直线切点）就走对齐模式：up/dn 是紧裁字形，按切点两侧墨框贴入。"""
    import torch
    from common import INK_TH
    W = (win < INK_TH).astype(np.uint8)
    cimg, _, s = to_canvas(win, top=8)
    if align_cut is not None:
        ba, bb = eval_boxes(win, align_cut, s, 8)
        x = make_input_v3a(cimg, up, dn, ba, bb)[None].to(dev)
    else:
        x = make_input_v3(cimg, up, dn)[None].to(dev)
    with torch.no_grad():
        prob = torch.softmax(net(x)[0], 0).cpu().numpy()
    prob = prob[:, 8:]
    h, w = win.shape
    if s < 1.0:
        ph, pw = int(h * s), int(w * s)
        prob = np.stack([cv2.resize(prob[k][:ph, :pw], (w, h), interpolation=cv2.INTER_LINEAR) for k in range(prob.shape[0])])
    else:
        prob = prob[:, :h, :w]
    pA, pB = prob[1], prob[2]
    raw = np.where(W > 0, np.where(pA >= pB, 1, 2), 0).astype(np.uint8)
    conf = np.abs(pA - pB)
    owner = raw.copy()
    n_cc, lab, st, _ = cv2.connectedComponentsWithStats(W, connectivity=8)
    for i in range(1, n_cc):
        if cc_max is not None and st[i, cv2.CC_STAT_AREA] > cc_max:
            continue
        m = lab == i
        v = raw[m]
        nA, nB = int((v == 1).sum()), int((v == 2).sum())
        if nA >= 0.85 * (nA + nB):
            owner[m] = 1
        elif nB >= 0.85 * (nA + nB):
            owner[m] = 2
    return W, owner, conf


# ── 训练 ──
def train(a) -> Path:
    import torch
    import torch.nn.functional as F
    gb = GlyphBank()
    roots = [Path(p) for p in a.data.split(",")]
    metas = []
    for root in roots:
        for l in (root / "meta.jsonl").read_text(encoding="utf-8").splitlines():
            metas.append((root, json.loads(l)))
    random.Random(0).shuffle(metas)
    if a.limit:
        metas = metas[: a.limit]
    n_val = max(300, len(metas) // 25)
    t0 = time.time()
    items = []
    n_glyph = 0
    for root, m in metas:
        g = cv2.imread(str(root / "pairs" / f"{m['i']:06d}.png"), 0)
        o = cv2.imread(str(root / "pairs" / f"{m['i']:06d}_own.png"), 0)
        if g is None or o is None:
            continue
        up = gb.get_raw(m["A"].get("label")) if a.align else gb.get(m["A"].get("label"))
        dn = gb.get_raw(m["B"].get("label")) if a.align else gb.get(m["B"].get("label"))
        n_glyph += int(up is not None) + int(dn is not None)
        items.append((g, o, up, dn))
    val, tr = items[:n_val], items[n_val:]
    print(f"预载 {len(items)} 对，字形可用 {n_glyph}/{2 * len(items)}，{time.time() - t0:.0f}s", flush=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model_v3().to(dev)
    init_from_v2(net, dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    steps_per_ep = len(tr) // a.bs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * steps_per_ep, pct_start=0.1)
    cw = torch.tensor([0.2, 1.0, 1.0], device=dev)
    ck = MODEL_DIR / ("partition_unet_v3a.pt" if a.align else "partition_unet_v3.pt")
    best = 1e9
    rng = random.Random(7)

    def sample(g, o, up, dn, augment: bool):
        top = 0
        if augment:
            sy = random.uniform(0.85, 1.05); sx = random.uniform(0.95, 1.03)
            if abs(sy - 1) > 0.01 or abs(sx - 1) > 0.01:
                g = cv2.resize(g, (max(8, int(g.shape[1] * sx)), max(8, int(g.shape[0] * sy))), interpolation=cv2.INTER_AREA)
                o = cv2.resize(o, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
            dx = random.randint(0, 8)
            g = np.pad(g, ((0, 0), (dx, 0)), constant_values=255); o = np.pad(o, ((0, 0), (dx, 0)), constant_values=0)
            top = random.randint(0, 40)
            if random.random() < a.drop:                    # 没有身份也要能工作
                up, dn = None, None
        img, own, _ = to_canvas(g, o, top=top)
        y = torch.from_numpy(own.astype(np.int64)); y[y == 3] = -1
        if a.align:
            ba = bbox_of((own == 1) | (own == 3))
            bb = bbox_of((own == 2) | (own == 3))
            if augment:
                ba, bb = jitter_box(ba, rng), jitter_box(bb, rng)
            return make_input_v3a(img, up, dn, ba, bb), y
        return make_input_v3(img, up, dn), y

    print(f"train {len(tr)} / val {len(val)} device={dev} epochs={a.epochs} steps={a.epochs * steps_per_ep}", flush=True)
    for ep in range(a.epochs):
        net.train(); random.shuffle(tr); tot = 0.0; n = 0
        for i in range(0, len(tr) - a.bs + 1, a.bs):
            xs, ys = zip(*[sample(*it, True) for it in tr[i: i + a.bs]])
            x = torch.stack(xs).to(dev); y = torch.stack(ys).to(dev)
            loss = F.cross_entropy(net(x), y, weight=cw, ignore_index=-1)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += float(loss) * x.size(0); n += x.size(0)
        net.eval(); vt = 0.0; vn = 0; err_px = []; blob150 = []
        with torch.no_grad():
            for i in range(0, len(val), 32):
                xs, ys = zip(*[sample(*it, False) for it in val[i: i + 32]])
                x = torch.stack(xs).to(dev); y = torch.stack(ys).to(dev)
                lg = net(x)
                vt += float(F.cross_entropy(lg, y, weight=cw, ignore_index=-1)) * x.size(0); vn += x.size(0)
                pred = lg.argmax(1); m = (y > 0); e = ((pred != y) & m)
                err_px += e.flatten(1).sum(1).float().tolist()
                for k in range(e.size(0)):
                    em = e[k].cpu().numpy().astype(np.uint8)
                    if em.any():
                        _, _, st, _ = cv2.connectedComponentsWithStats(em, connectivity=8)
                        blob150.append(int(st[1:, cv2.CC_STAT_AREA].max() >= 150))
                    else:
                        blob150.append(0)
        vloss = vt / vn
        print(f"ep {ep + 1}/{a.epochs} train {tot / n:.4f} val {vloss:.4f} val_err_px mean {np.mean(err_px):.1f} median {np.median(err_px):.0f} blob>=150 {np.mean(blob150):.1%}  {time.time() - t0:.0f}s", flush=True)
        if vloss < best:
            best = vloss
            torch.save({"state": net.state_dict(), "canvas": (CANVAS_H, CANVAS_W), "v": 3}, ck)
    print(f"→ {ck}", flush=True)
    return ck


# ── 金标评测 ──
def eval_gold(a) -> None:
    import torch
    from common import Loader, OUT_ROOT, jdump, seam_chosen, seam_gold, seams_candidates, window
    from exp3_partition_eval import err_stats
    from exp7_select_pool import dis_blob
    from templates import owner_from_seam
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model_v3().to(dev)
    default_ck = MODEL_DIR / ("partition_unet_v3a.pt" if a.align else "partition_unet_v3.pt")
    net.load_state_dict(torch.load(Path(a.ckpt) if a.ckpt else default_ck, map_location=dev)["state"])
    net.eval()
    gb = GlyphBank()
    L = Loader()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    base7 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp7" / "per_case.json").read_text(encoding="utf-8"))}
    tag = "unet_v3a" if a.align else "unet_v3"
    out = OUT_ROOT / (f"{tag}_cc{a.cc_max}" if a.cc_max is not None else tag)
    (out / "viz").mkdir(parents=True, exist_ok=True)
    per = []
    keep = []
    for it in L.gold_items(books=a.books.split(",")):
        if it.id not in frame_ok:
            continue
        c, _ = L.resolve(it)
        if c is None or L.image_of(c) is None:
            continue
        rk = (exp1.get(c.id) or {}).get("rank", {}).get("gold", {})
        label_ok = bool(rk.get("fused_above") and rk["fused_above"] <= 5 and rk.get("fused_below") and rk["fused_below"] <= 5)
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        cut = int(round(c.straight_y - y0)) if a.align else None
        if a.align:
            up, dn = gb.get_raw(c.char_above), gb.get_raw(c.char_below)
        else:
            up, dn = gb.get(c.char_above), gb.get(c.char_below)
        W, o3, conf = owner_v3(net, dev, win, up, dn, a.cc_max, align_cut=cut)
        _, o3n, _ = owner_v3(net, dev, win, None, None, a.cc_max, align_cut=cut)        # 消融：无身份
        ink = W > 0
        cw = conf[ink]
        og = owner_from_seam(W, seam_gold(c) - y0)
        sc = seam_chosen(c)
        members = []
        seen = []
        for kind, seam in seams_candidates(c):
            key = tuple(int(v) for v in seam)
            if key in seen:
                continue
            seen.append(key)
            o = owner_from_seam(W, seam - y0)
            n, blob = err_stats(o, og)
            eq = (o[ink] == o3[ink])
            members.append({"kind": kind, "is_chosen": bool(np.array_equal(seam, sc)), "err": {"px": n, "blob": blob},
                            "agree_w": float((cw * eq).sum() / max(cw.sum(), 1e-6)) if eq.size else 1.0, "dis_unet": dis_blob(o, o3, W)})
        if not any(m["is_chosen"] for m in members):
            oc = owner_from_seam(W, sc - y0)
            n, blob = err_stats(oc, og)
            eq = (oc[ink] == o3[ink])
            members.append({"kind": "chosen", "is_chosen": True, "err": {"px": n, "blob": blob},
                            "agree_w": float((cw * eq).sum() / max(cw.sum(), 1e-6)), "dis_unet": dis_blob(oc, o3, W)})
        n3, b3 = err_stats(o3, og)
        n3n, b3n = err_stats(o3n, og)
        rec = {"id": c.id, "verdict": c.verdict, "book": c.book, "label_ok": label_ok,
               "glyph": [up is not None, dn is not None], "chars": c.char_above + c.char_below,
               "unet_v3": {"px": n3, "blob": b3}, "unet_v3_noid": {"px": n3n, "blob": b3n},
               "unet_v2": (base7.get(c.id) or {}).get("unet"), "members": members}
        per.append(rec)
        keep.append((rec, win, og, o3))
    jdump(per, out / "per_case.json")

    def agg(errs):
        errs = [e for e in errs if e]
        px = np.array([e["px"] for e in errs]); bl = np.array([e["blob"] for e in errs])
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4),
                "blob_ge150": round(float((bl >= 150).mean()), 4)}

    def fmt(x):
        return f"{x['px_mean']:7.1f} {x['px_median']:6.0f} {x['le20px']:7.1%} {x['blob_ge60']:8.1%} {x['blob_ge150']:8.1%}"

    def chosen(r):
        return next(m for m in r["members"] if m["is_chosen"])["err"]

    def s1m(r):
        return max(r["members"], key=lambda m: (m["agree_w"], m["is_chosen"]))

    def S1U(T):
        def f(r):
            b = s1m(r)
            return r["unet_v3"] if b["dis_unet"] >= T else b["err"]
        return f

    def best_cand(r):
        return min((m["err"] for m in r["members"]), key=lambda e: (e["blob"], e["px"]))

    def oracle(r):
        return min([m["err"] for m in r["members"]] + [r["unet_v3"]], key=lambda e: (e["blob"], e["px"]))

    methods = {"chosen": chosen, "unet_v2": lambda r: r["unet_v2"], "unet_v3(身份)": lambda r: r["unet_v3"],
               "unet_v3 无身份消融": lambda r: r["unet_v3_noid"], "S1 用v3当裁判": lambda r: s1m(r)["err"],
               "S1+U(150) v3": S1U(150), "S1+U(100) v3": S1U(100), "候选池上限": best_cand, "全池上限(+v3)": oracle}
    rows = [r for r in per if r["label_ok"]]
    summary = {"n_frame_ok": len(per), "n_label_ok": len(rows), "cc_max": a.cc_max,
               "glyph_coverage": round(float(np.mean([all(r["glyph"]) for r in rows])), 4), "label_ok": {}, "by_verdict": {}}
    print(f"\nlabel_ok n={len(rows)}，两字字形都渲染出来的 {summary['glyph_coverage']:.1%}")
    print(f"{'method':22s} px_mean median  le20px  blob>=60 blob>=150")
    for name, f in methods.items():
        x = agg([f(r) for r in rows]); summary["label_ok"][name] = x
        print(f"{name:22s} {fmt(x)}")
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        summary["by_verdict"][v] = {name: agg([f(r) for r in rr]) for name, f in methods.items()}
        print(f"-- {v} n={len(rr)} blob>=150: " + "  ".join(f"{m}={summary['by_verdict'][v][m]['blob_ge150']:.1%}" for m in ("chosen", "unet_v2", "unet_v3(身份)", "unet_v3 无身份消融", "S1 用v3当裁判", "S1+U(150) v3")))
    jdump(summary, out / "summary.json")
    worst = sorted([p for p in keep if p[0]["label_ok"]], key=lambda p: -p[0]["unet_v3"]["blob"])[:24]
    for rec, win, og, o3 in worst:
        vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR); panels = []
        for o in (og, o3):
            ov = vis.copy(); ov[o == 1] = (0, 0, 220); ov[o == 2] = (220, 90, 0)
            panels.append(cv2.addWeighted(vis, 0.35, ov, 0.65, 0))
        cv2.imwrite(str(out / "viz" / (rec["id"].replace(":", "_") + ".png")),
                    cv2.resize(np.concatenate([vis] + panels, axis=1), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    print(f"→ {out}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true"); ap.add_argument("--eval-gold", action="store_true")
    ap.add_argument("--data", default="D:/data/touch_synth/vol01,D:/data/touch_synth/vol02")
    ap.add_argument("--epochs", type=int, default=6); ap.add_argument("--bs", type=int, default=24); ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--drop", type=float, default=0.15, help="训练时随机抹掉字形通道的比例")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ckpt", default=None); ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--cc-max", type=int, default=400)
    ap.add_argument("--align", action="store_true", help="字形按字框对齐贴入（v3a），而不是贴在画布顶/底")
    a = ap.parse_args()
    if a.train:
        train(a)
    if a.eval_gold:
        eval_gold(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
