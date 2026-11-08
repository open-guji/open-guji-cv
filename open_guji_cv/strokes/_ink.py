"""笔画识别的底层图像与几何工具：二值化、细化、骨架图、剪毛刺、折线几何。

只依赖 numpy、cv2（不依赖 skimage / networkx：cv 核心依赖里没有它们）。坐标一律 (y, x)。
"""
from __future__ import annotations

import math

import cv2
import numpy as np

# ---------------------------------------------------------------- 预处理

def binarize(gray: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = (b > 0).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    keep = np.zeros(n, bool)
    if n > 1:
        big = st[1:, cv2.CC_STAT_AREA].max()
        keep[1:] = st[1:, cv2.CC_STAT_AREA] >= max(12, 0.01 * big)
    b = keep[lab].astype(np.uint8)
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return b


def clean_cell(ink: np.ndarray, edge_frac: float = 0.15, line_aspect: float = 8.0) -> np.ndarray:
    """去掉字块里不属于本字的墨：贴着字块边、墨量不到全字 edge_frac 的连通块（邻字伸进来的笔头、切进来的碎墨），
    以及贴边的细长直线（界栏、框线）。字块按页裁、外扩几像素时常带这些。"""
    H, W = ink.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    if n <= 2:
        return ink
    total = st[1:, cv2.CC_STAT_AREA].sum()
    keep = np.ones(n, bool)
    keep[0] = False
    for i in range(1, n):
        x, y, w, h, a = st[i]
        edge = x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1
        if not edge:
            continue
        thin_line = max(w, h) >= line_aspect * min(w, h) and max(w / W, h / H) >= 0.5
        if a < edge_frac * total or thin_line:
            keep[i] = False
    if not keep.any():
        return ink
    return keep[lab].astype(np.uint8)


def stroke_width(ink: np.ndarray, skel: np.ndarray) -> float:
    dt = cv2.distanceTransform(ink, cv2.DIST_L2, 5)
    v = dt[skel > 0]
    return float(2 * np.median(v)) if len(v) else 6.0

# ---------------------------------------------------------------- 骨架图

def _zs_lut(step: int) -> np.ndarray:
    """Zhang-Suen 细化的 256 项查找表：邻域 8 位码 → 这一子步删不删中心像素。"""
    lut = np.zeros(256, bool)
    for code in range(256):
        p = [(code >> i) & 1 for i in range(8)]  # P2..P9：上、右上、右、右下、下、左下、左、左上
        b = sum(p)
        a = sum(p[i] == 0 and p[(i + 1) % 8] == 1 for i in range(8))
        p2, p4, p6, p8 = p[0], p[2], p[4], p[6]
        if step == 0:
            c = p2 * p4 * p6 == 0 and p4 * p6 * p8 == 0
        else:
            c = p2 * p4 * p8 == 0 and p2 * p6 * p8 == 0
        lut[code] = 2 <= b <= 6 and a == 1 and c
    return lut


_LUT = (_zs_lut(0), _zs_lut(1))
_NBW = np.array([[128, 1, 2], [64, 0, 4], [32, 16, 8]], np.float32)  # P9 P2 P3 / P8 · P4 / P7 P6 P5


def thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen 细化成单像素骨架（8 连通）。纯 numpy＋cv2，结果确定。"""
    sk = (np.asarray(mask) > 0).astype(np.uint8)
    while True:
        changed = False
        for step in (0, 1):
            code = cv2.filter2D(sk.astype(np.float32), -1, _NBW, borderType=cv2.BORDER_CONSTANT)
            kill = _LUT[step][np.rint(code).astype(np.int32)] & (sk > 0)
            if kill.any():
                sk[kill] = 0
                changed = True
        if not changed:
            return sk


NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _deg(sk):
    k = np.ones((3, 3), np.uint8)
    k[1, 1] = 0
    return cv2.filter2D(sk.astype(np.uint8), -1, k, borderType=cv2.BORDER_CONSTANT) * sk


def build_graph(sk: np.ndarray):
    """返回 nodes{id:(y,x)}, edges[(a,b,path[(y,x)...])]。path 从 a 走到 b。"""
    H, W = sk.shape
    deg = _deg(sk)
    jmask = ((deg >= 3) & (sk > 0)).astype(np.uint8)
    emask = ((deg == 1) & (sk > 0))
    nj, jl = cv2.connectedComponents(jmask, connectivity=8)
    node_of = -np.ones(sk.shape, int)
    nodes = {}
    nid = 0
    for j in range(1, nj):
        ys, xs = np.nonzero(jl == j)
        node_of[ys, xs] = nid
        nodes[nid] = (float(ys.mean()), float(xs.mean()))
        nid += 1
    for y, x in zip(*np.nonzero(emask)):
        node_of[y, x] = nid
        nodes[nid] = (float(y), float(x))
        nid += 1
    visited = np.zeros(sk.shape, bool)
    edges = []

    def nbrs(y, x):
        for dy, dx in NB:
            yy, xx = y + dy, x + dx
            if 0 <= yy < H and 0 <= xx < W and sk[yy, xx]:
                yield yy, xx

    # 从每个节点像素出发走边
    for y0, x0 in zip(*np.nonzero(node_of >= 0)):
        a = node_of[y0, x0]
        for y1, x1 in nbrs(y0, x0):
            if node_of[y1, x1] == a:
                continue
            if node_of[y1, x1] >= 0:  # 两节点直接相邻
                b = node_of[y1, x1]
                if a < b:
                    edges.append((a, b, [(y0, x0), (y1, x1)]))
                continue
            if visited[y1, x1]:
                continue
            path = [(y0, x0), (y1, x1)]
            visited[y1, x1] = True
            py, px = y0, x0
            cy, cx = y1, x1
            end = None
            while True:
                nxt = None
                for yy, xx in nbrs(cy, cx):
                    if (yy, xx) == (py, px):
                        continue
                    if node_of[yy, xx] >= 0 and node_of[yy, xx] != -1:
                        if (yy, xx) != (y0, x0) or len(path) > 2:
                            end = (yy, xx)
                            break
                    if not visited[yy, xx] and node_of[yy, xx] < 0:
                        nxt = (yy, xx)
                if end is not None:
                    path.append(end)
                    break
                if nxt is None:
                    break
                visited[nxt] = True
                path.append(nxt)
                py, px, cy, cx = cy, cx, nxt[0], nxt[1]
            if end is not None:
                edges.append((a, node_of[end], path))
    # 去重（两端各走一次会重复的直接相邻边已按 a<b 去掉；普通边因 visited 只走一次）
    # 没有节点的闭环（如四角都是 L 的口）
    rest = (sk > 0) & ~visited & (node_of < 0)
    while rest.any():
        y0, x0 = map(int, np.argwhere(rest)[0])
        node_of[y0, x0] = nid
        nodes[nid] = (float(y0), float(x0))
        path = [(y0, x0)]
        visited[y0, x0] = True
        cy, cx = y0, x0
        while True:
            nxt = None
            for yy, xx in nbrs(cy, cx):
                if not visited[yy, xx]:
                    nxt = (yy, xx)
                    break
            if nxt is None:
                break
            visited[nxt] = True
            path.append(nxt)
            cy, cx = nxt
        path.append((y0, x0))
        edges.append((nid, nid, path))
        nid += 1
        rest = (sk > 0) & ~visited & (node_of < 0)
    return nodes, edges


def prune_spurs(sk: np.ndarray, maxlen: float, rounds: int = 3) -> np.ndarray:
    """去掉一头悬空、一头连在交叉点上的短枝（刻本横末三角、顿笔、毛边）。"""
    sk = sk.copy()
    for _ in range(rounds):
        nodes, edges = build_graph(sk)
        degc = {}
        for a, b, _ in edges:
            degc[a] = degc.get(a, 0) + 1
            degc[b] = degc.get(b, 0) + 1
        removed = False
        for a, b, p in edges:
            if a == b:
                continue
            da, db = degc.get(a, 0), degc.get(b, 0)
            if (da == 1) != (db == 1) and len(p) < maxlen:
                tip_is_a = da == 1
                for (y, x) in (p[:-1] if tip_is_a else p[1:]):
                    sk[y, x] = 0
                removed = True
        sk = thin(sk)
        if not removed:
            break
    return sk

# ---------------------------------------------------------------- 几何工具

def arclen(path):
    p = np.asarray(path, float)
    return float(np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1))) if len(p) > 1 else 0.0


def point_at(path, d):
    p = np.asarray(path, float)
    acc = 0.0
    for i in range(1, len(p)):
        s = np.linalg.norm(p[i] - p[i - 1])
        if acc + s >= d:
            t = (d - acc) / s if s else 0
            return p[i - 1] + t * (p[i] - p[i - 1])
        acc += s
    return p[-1]


def out_dir(path, w):
    """从 path[0] 出发的方向（单位向量，(dy,dx)），避开交叉点附近的骨架畸变。"""
    L = arclen(path)
    d0 = min(0.6 * w, L * 0.25)
    d1 = min(3.0 * w, L * 0.8)
    v = point_at(path, d1) - point_at(path, d0)
    n = np.linalg.norm(v)
    return v / n if n else np.array([0.0, 1.0])


def ang_between(u, v):
    return math.degrees(math.acos(max(-1, min(1, float(np.dot(u, v))))))


def rdp(pts, eps):
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return list(range(len(pts)))
    a, b = pts[0], pts[-1]
    ab = b - a
    n = np.linalg.norm(ab)
    if n == 0:
        d = np.linalg.norm(pts - a, axis=1)
    else:
        d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / n
    i = int(np.argmax(d))
    if d[i] > eps:
        l = rdp(pts[: i + 1], eps)
        r = rdp(pts[i:], eps)
        return l[:-1] + [j + i for j in r]
    return [0, len(pts) - 1]



def extend_tip(ink, p, d, maxstep):
    """从 p 沿方向 d 走到墨边（最多 maxstep 步）。"""
    y, x = p
    for _ in range(int(maxstep)):
        ny, nx_ = y + d[0], x + d[1]
        iy, ix = int(round(ny)), int(round(nx_))
        if not (0 <= iy < ink.shape[0] and 0 <= ix < ink.shape[1]) or not ink[iy, ix]:
            break
        y, x = ny, nx_
    return (y, x)


def resample(pts, step):
    """折线按弧长等距重采样。"""
    pts = np.asarray(pts, float)
    if len(pts) < 2:
        return pts
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    L = np.concatenate([[0], np.cumsum(seg)])
    n = max(2, int(L[-1] / step) + 1)
    t = np.linspace(0, L[-1], n)
    return np.stack([np.interp(t, L, pts[:, 0]), np.interp(t, L, pts[:, 1])], 1)


def ink_bbox(ink: np.ndarray):
    """墨的外框 (y0, x0, y1, x1)；没墨返回整图。"""
    ys, xs = np.nonzero(ink)
    if not len(ys):
        return (0.0, 0.0, float(ink.shape[0] - 1), float(ink.shape[1] - 1))
    return (float(ys.min()), float(xs.min()), float(ys.max()), float(xs.max()))
