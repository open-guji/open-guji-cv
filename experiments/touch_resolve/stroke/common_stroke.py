# -*- coding: utf-8 -*-
"""stroke/ 目录的公共件：U-Net v2 推理、连通体多数票、缝→owner、错归属尺子、四联对照图。
从 templates.py / exp3_partition_eval.py / train_partition_unet_v2.py 抄来的部分不改语义（那些文件不动）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
TR = HERE.parent                                   # experiments/touch_resolve
for p in (str(TR), str(TR.parents[1])):
    if p not in sys.path:
        sys.path.insert(0, p)

from common import INK_TH, OUT_ROOT  # noqa: E402
from train_partition_unet_v2 import MODEL_DIR, build_model, make_input, to_canvas  # noqa: E402

STROKE_OUT = OUT_ROOT / "stroke_eval"


# ───────── U-Net v2 ─────────
class UNetV2:
    def __init__(self, ckpt: Path | None = None, device: str | None = None):
        import torch
        self.torch = torch
        ck = Path(ckpt) if ckpt else MODEL_DIR / "partition_unet_v2.pt"
        self.dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.net = build_model().to(self.dev)
        self.net.load_state_dict(torch.load(ck, map_location=self.dev)["state"])
        self.net.eval()
        self.ckpt = ck

    def predict(self, win: np.ndarray) -> np.ndarray:
        """窗口灰度 → 与窗口同形的 argmax 类别图（0 背景 1 上字 2 下字），未按墨掩膜。"""
        cimg, _, s = to_canvas(win, top=8)
        x = make_input(cimg)[None].to(self.dev)
        with self.torch.no_grad():
            pred = self.net(x).argmax(1)[0].cpu().numpy().astype(np.uint8)
        pred = pred[8:]
        h, w = win.shape
        if s < 1.0:
            ph, pw = int(h * s), int(w * s)
            pred = cv2.resize(pred[:ph, :pw], (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            pred = pred[:h, :w]
        return pred


def raw_owner_from_pred(pred: np.ndarray, W: np.ndarray) -> np.ndarray:
    """B 的口径：墨上 pred==0 记作下字（2）。"""
    return np.where(W > 0, np.where(pred == 0, 2, pred), 0).astype(np.uint8)


def cc_vote(raw_owner: np.ndarray, W: np.ndarray, th: float = 0.85) -> np.ndarray:
    """连通体多数票平滑（与 train_partition_unet_v2.eval_gold / templates.Registrar.partition 同精神）。"""
    owner = raw_owner.copy()
    n_cc, lab = cv2.connectedComponents(W.astype(np.uint8), connectivity=8)
    for i in range(1, n_cc):
        m = lab == i; v = raw_owner[m]; nA, nB = int((v == 1).sum()), int((v == 2).sum())
        if nA + nB == 0:
            continue
        if nA >= th * (nA + nB):
            owner[m] = 1
        elif nB >= th * (nA + nB):
            owner[m] = 2
    return owner


# ───────── 缝 / 尺子（抄自 templates.owner_from_seam、exp3.err_stats）─────────
def owner_from_seam(win_ink: np.ndarray, seam_local: np.ndarray) -> np.ndarray:
    h, w = win_ink.shape
    ys = np.arange(h)[:, None]
    above = ys < np.asarray(seam_local[:w])[None, :]
    owner = np.where(above, 1, 2).astype(np.uint8)
    owner[win_ink == 0] = 0
    return owner


def err_stats(o: np.ndarray, og: np.ndarray) -> tuple[int, int]:
    m = (og > 0) & (o > 0) & (o != og)
    n = int(m.sum())
    if n == 0:
        return 0, 0
    k, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    return n, int(stats[1:, cv2.CC_STAT_AREA].max())


# ───────── 画图 ─────────
_FONT = None


def _font(size: int):
    global _FONT
    if _FONT is None:
        try:
            from PIL import ImageFont
            fp = TR.parents[1] / "fonts" / "iming" / "I.Ming-8.10.ttf"
            _FONT = ImageFont.truetype(str(fp), size) if fp.exists() else ImageFont.load_default()
        except Exception:
            _FONT = False
    return _FONT


def tint(win: np.ndarray, owner: np.ndarray) -> np.ndarray:
    """红=上字 蓝=下字，灰底。"""
    vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
    ov = vis.copy(); ov[owner == 1] = (0, 0, 220); ov[owner == 2] = (220, 90, 0)
    return cv2.addWeighted(vis, 0.35, ov, 0.65, 0)


def sheet(win: np.ndarray, panels: list[tuple[str, np.ndarray | None]], title: str, scale: int = 2,
          extra: list[np.ndarray] | None = None) -> np.ndarray:
    """左原图 + 各归属着色 + 可选额外面板，顶上一行标题（PIL 写中文）。"""
    cols = [cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)] + [tint(win, o) if o is not None else np.full((*win.shape, 3), 255, np.uint8) for _, o in panels]
    cols = [cv2.resize(c, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST) for c in cols]
    if extra:
        for e in extra:
            H = cols[0].shape[0]
            if e.shape[0] != H:
                e = cv2.resize(e, (int(e.shape[1] * H / e.shape[0]), H), interpolation=cv2.INTER_NEAREST)
            cols.append(e)
    gap = np.full((cols[0].shape[0], 6, 3), 255, np.uint8)
    body = np.concatenate(sum([[c, gap] for c in cols], [])[:-1], axis=1)
    head = np.full((44, body.shape[1], 3), 255, np.uint8)
    labels = ["原图"] + [n for n, _ in panels]
    f = _font(15)
    if f:
        from PIL import Image, ImageDraw
        im = Image.fromarray(head); d = ImageDraw.Draw(im)
        d.text((4, 2), title, fill=(0, 0, 0), font=f)
        x = 0
        for i, c in enumerate(cols):
            if i < len(labels):
                d.text((x + 4, 24), labels[i], fill=(60, 60, 60), font=f)
            x += c.shape[1] + 6
        head = np.array(im)
    else:
        cv2.putText(head, title.encode("ascii", "replace").decode(), (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return np.concatenate([head, body], axis=0)
