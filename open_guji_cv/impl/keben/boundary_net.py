"""字间界线判官（2026-11-26，CV2）：小 CNN 看切线上下各一格的图，判「这里是不是两个字之间」，只用来**重排正文列内部切线**。

缘起：写本（史記文淵閣本）大小字不匀，上下结构的高字字内有白缝（⺮｜官、宀｜寸），DP 在等距先验下把格线放进字内白缝；
这种线不劈连通块、两格 U-Net 一致率也高，纯几何分不出来（ai-team `domain/CV/A22/cut-bench/实验-三书修复-1124.md`）。
判官是「看字」的第二意见：用本书别的册的生产产物（含人钉列）当银标训的二分类，正样本＝相邻两字格的界线（及同一条干净白缝里的
别处），负样本＝离界线 ≥0.2 格距的行墨谷。

用法（`refine_bounds`）：格数不变；只动「上下两格都是正文字」的内部线；每条线在 ±`WIN`×period 内取行墨谷作候选
（要与现线隔着墨——同一条白缝里挪动没有意义），现线判官分 < `p_old` 的才许挪；一列一个小 DP 选线：
代价＝(1−判官分) ＋ 格高偏离 period 的平方×`PITCH_W` ＋ 挪动罚 `MOVE_PEN`。没挪返回 None。

模型：`models/<名>/model.pt`（state_dict，结构见 `_net`），窗口 2×period 高、内容窗口宽，缩到 64×96，灰度反相。
训练与评测脚本：ai-team `domain/CV/A22/cut-bench/boundary-net/`。
"""
from __future__ import annotations

import functools
from pathlib import Path

import cv2
import numpy as np

PW, PH = 64, 96          # 判官输入（宽 × 高）
WIN = 0.6                # 候选窗口半宽（× period）
MIN_CELL = 0.35          # 重排后格高下限（× period）
GAP_INK = 0.06           # 候选与现线之间行墨（5 行平滑、占内容宽比例）最大值要超过它，才算换了一条缝
PITCH_W = 0.5            # 格高偏离代价权重
MOVE_PEN = 0.05          # 挪动罚
INK_THRESHOLD = 128


def _net():
    import torch.nn as nn
    return nn.Sequential(
        nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((3, 2)),
        nn.Flatten(), nn.Linear(384, 64), nn.ReLU(), nn.Linear(64, 1))


def model_path(name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "models" / name / "model.pt"


@functools.lru_cache(maxsize=4)
def load(name: str):
    import torch
    torch.set_num_threads(1)
    m = _net()
    m.load_state_dict(torch.load(model_path(name), map_location="cpu", weights_only=True))
    m.eval()
    return m


def _patch(gcol: np.ndarray, y: float, period: float) -> np.ndarray:
    h = gcol.shape[0]
    y0, y1 = int(round(y - period)), int(round(y + period))
    win = gcol[max(0, y0):min(h, y1)]
    win = cv2.copyMakeBorder(win, max(0, -y0), max(0, y1 - h), 0, 0, cv2.BORDER_CONSTANT, value=255)
    return cv2.resize(win, (PW, PH), interpolation=cv2.INTER_AREA)


def score(name: str, gcol: np.ndarray, ys, period: float) -> np.ndarray:
    import torch
    if not len(ys):
        return np.zeros(0)
    x = np.stack([_patch(gcol, y, period) for y in ys]).astype(np.float32)
    x = torch.from_numpy(1.0 - x / 255.0).unsqueeze(1)
    with torch.no_grad():
        return torch.sigmoid(load(name)(x).squeeze(1)).numpy()


def _valleys(curve: np.ndarray, min_sep: int = 6) -> list[int]:
    c = np.convolve(curve, np.ones(5) / 5, mode="same")
    out: list[int] = []
    for i in range(2, len(c) - 2):
        if c[i] <= c[i - 1] and c[i] <= c[i + 1] and (c[i] < c[i - 2] or c[i] < c[i + 2] or c[i] == 0):
            if out and i - out[-1] < min_sep:
                if c[i] < c[out[-1]]:
                    out[-1] = i
                continue
            out.append(i)
    return out


def refine_bounds(name: str, col_gray: np.ndarray, content_x, cells, period: float,
                  p_old: float) -> tuple[list[tuple[int, float]], list[tuple[int, int, float, float]]] | None:
    """返回 (要改的线 [(k, 新 y)], 记录 [(k, 旧 y, 新 y, 旧分, 新分)])；不改返回 None。
    k 是第 k 个「正文字｜正文字」界（按 y 排序的相邻格对，上格下沿＝下格上沿那条线）。"""
    body = sorted((c for c in cells if c.kind != "blank"), key=lambda c: c.y0)
    if len(body) < 4 or any(c.kind != "char" for c in body):
        return None
    x_lo, x_hi = (int(round(content_x[0])), int(round(content_x[1]))) if content_x else (0, col_gray.shape[1])
    gcol = col_gray[:, max(0, x_lo):max(x_lo + 1, x_hi)]
    curve = (gcol < INK_THRESHOLD).mean(axis=1)
    cs = np.convolve(curve, np.ones(5) / 5, mode="same")
    lines = [body[0].y0] + [(body[i - 1].y1 + body[i].y0) / 2 for i in range(1, len(body))] + [body[-1].y1]
    inner = list(range(1, len(lines) - 1))
    cur = [int(round(lines[i])) for i in inner]
    p_cur = score(name, gcol, cur, period)
    cands: list[list[int]] = []
    for j, i in enumerate(inner):
        y0 = cur[j]
        cc = [y0]
        if p_cur[j] < p_old and abs(body[i - 1].y1 - body[i].y0) < 3:
            lo = int(max(lines[i - 1] + MIN_CELL * period, y0 - WIN * period))
            hi = int(min(lines[i + 1] - MIN_CELL * period, y0 + WIN * period))
            for v in _valleys(curve[max(0, lo):max(0, hi)]):
                v += max(0, lo)
                a, b = sorted((v, y0))
                if cs[a:b + 1].max() > GAP_INK:
                    cc.append(v)
        cands.append(sorted(set(cc)))
    if all(len(c) == 1 for c in cands):
        return None
    extra = sorted({y for c in cands for y in c} - set(cur))
    pm = dict(zip(cur, p_cur))
    pm.update(zip(extra, score(name, gcol, extra, period)))

    def unit(j, y):
        return (1.0 - pm[y]) + (MOVE_PEN if y != cur[j] else 0.0)

    def pitch(h):
        return PITCH_W * ((h - period) / period) ** 2

    INF = float("inf")
    n = len(cands)
    cost = [{y: INF for y in c} for c in cands]
    back: list[dict] = [{} for _ in cands]
    for y in cands[0]:
        cost[0][y] = unit(0, y) + pitch(y - lines[0])
    for j in range(1, n):
        for y in cands[j]:
            best = (INF, None)
            for py, v in cost[j - 1].items():
                if v == INF or y - py < MIN_CELL * period:
                    continue
                t = v + pitch(y - py)
                if t < best[0]:
                    best = (t, py)
            if best[1] is not None:
                cost[j][y] = best[0] + unit(j, y)
                back[j][y] = best[1]
    end = min(((v + pitch(lines[-1] - y), y) for y, v in cost[-1].items() if v < INF), default=None)
    if end is None:
        return None
    path = [end[1]]
    for j in range(n - 1, 0, -1):
        path.append(back[j][path[-1]])
    path.reverse()
    moves = [(j, float(y)) for j, y in enumerate(path) if y != cur[j]]
    if not moves:
        return None
    log = [(j, cur[j], int(path[j]), round(float(pm[cur[j]]), 3), round(float(pm[path[j]]), 3)) for j, _ in moves]
    return moves, log
