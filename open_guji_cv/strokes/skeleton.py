"""不认字的骨架法：只看字图，切出每一笔的类型与起止点。

二值化 → 细化 → 骨架图（端点／交叉点为节点，剪毛刺、并近邻交叉点）
→ 交叉点处按「顺势穿过」配对，把被交叉点切断的同一笔接回来
→ 每条连笔在拐角处切段 → 段按方向分类（横竖撇捺点提）
→ 按笔画文法合成复合笔（横折、竖折、横撇…），封闭框里只合横折、横撇
→ 定书写方向，起止点沿笔势外推到墨边；残墨里再找点。

研究里量过（ai-team domain/CV/字形领域/笔画识别-研究-2026-11-07/）：1–4 笔的字笔数对约六成，5 笔以上崩，
所以**形近字判别不用它**，判别走 `register`（已知字码、贴模板）。这里留作诊断、无模板时的粗看。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from ._ink import (ang_between, arclen, binarize, build_graph, extend_tip, out_dir, prune_spurs,
                   stroke_width, thin)


@dataclass(frozen=True)
class SkelParams:
    upscale_to: int = 200          # 字身小于 160px 先放大到约这么大
    upscale_below: int = 160


def _has_path(adj: dict, a, b, skip_edge) -> bool:
    """无向多重图里不走 skip_edge 能否从 a 到 b（判边在不在环上）。"""
    seen, stack = {a}, [a]
    while stack:
        u = stack.pop()
        if u == b:
            return True
        for v, k in adj.get(u, ()):
            if k == skip_edge or v in seen:
                continue
            seen.add(v)
            stack.append(v)
    return False


# ---------------------------------------------------------------- 段与笔

def seg_class(vec, length, size):
    """vec=(dy,dx) 已按书写方向。返回 (类, 是否合法书写方向)。"""
    dy, dx = vec
    th = math.degrees(math.atan2(-dy, dx))  # 数学角，向右 0，向上 90
    short = length < 0.16 * size
    if -22 <= th <= 22:
        c, ok = "横", True
    elif -112 <= th <= -68:
        c, ok = "竖", True
    elif -168 < th < -112:
        c, ok = "撇", True
    elif -68 < th < -22:
        c, ok = "捺", True
    elif 22 < th <= 55:
        c, ok = "提", True
    else:  # 向左、向上、向左上：不是合法书写方向
        c, ok = "?", False
    if ok and c in ("撇", "竖") and length < 0.12 * size:
        c = "点"
    if ok and c == "捺" and length < 0.3 * size:
        c = "点"  # 捺是长笔；右下向的短笔当点（下、心）
    return c, ok, th


COMPOUND = {
    ("横", "竖"): "横折", ("横", "撇"): "横撇", ("竖", "横"): "竖折",
    ("竖", "提"): "竖提", ("撇", "点"): "撇点", ("撇", "提"): "撇折",
    ("横", "竖", "提"): "横折提", ("横", "竖", "横"): "横折折",
    ("竖", "横", "竖"): "竖折折", ("横", "撇", "捺"): "横撇弯钩",
    ("竖", "撇"): "撇",  # 竖撇（大、月的撇起笔竖直）
}
LOOP_OK = {("横", "竖"), ("横", "撇")}


@dataclass
class Stroke:
    pts: np.ndarray            # (n,2) y,x，按书写方向
    segs: list = field(default_factory=list)   # [(类, 起点idx, 终点idx)]
    name: str = ""
    start: tuple = (0, 0)
    end: tuple = (0, 0)
    corners: list = field(default_factory=list)


def split_corners(pts, w, turn=50):
    """开放折线上的拐角：用 ±k 窗口量转角，圆角也认得出；非极大抑制。"""
    P = np.asarray(pts, float)
    n = len(P)
    k = max(3, int(1.8 * w))
    if n < 2 * k + 1:
        return []
    tv = np.zeros(n)
    for i in range(k, n - k):
        u = P[i] - P[i - k]
        v = P[i + k] - P[i]
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if nu and nv:
            tv[i] = ang_between(u / nu, v / nv)
    cs = []
    for i in np.argsort(-tv):
        if tv[i] < turn:
            break
        if all(abs(int(i) - j) > k for j in cs):
            cs.append(int(i))
    return sorted(cs)


def _group(pts, cuts, w, size, in_loop, free_end=True):
    """pts 已定走向；cuts 拐角下标。返回 (笔画列表, 代价)。"""
    bounds = [0] + list(cuts) + [len(pts) - 1]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    infos = []
    for s, e in segs:
        v = pts[e] - pts[s]
        n = np.linalg.norm(v)
        c, ok, _ = seg_class(v / n if n else np.array([1.0, 0.0]), arclen(pts[s:e + 1]), size)
        infos.append((c, ok, arclen(pts[s:e + 1])))
    groups = [[0]]
    for i in range(1, len(segs)):
        prev = tuple(infos[j][0] for j in groups[-1])
        cand = prev + (infos[i][0],)
        ok_join = infos[i][1] and infos[i - 1][1] and cand in COMPOUND
        if cand[-2:] == ("竖", "横") and not (i == len(segs) - 1 and free_end):
            ok_join = False  # 竖折的横收笔应悬空（山、凵）；收在别的竖上多半是框底（日、目）
        if in_loop and cand not in LOOP_OK:
            ok_join = False  # 封闭框（口日目）里只认横折，左下角当竖、横两笔
        if ok_join:
            groups[-1].append(i)
        else:
            groups.append([i])
    out, bad = [], 0.0
    for g in groups:
        s, e = segs[g[0]][0], segs[g[-1]][1]
        sub = pts[s:e + 1]
        names = tuple(infos[j][0] for j in g)
        if len(names) == 1:
            nm = names[0]
            if not infos[g[0]][1]:  # 单段走向不合法：整笔翻过来
                sub = sub[::-1]
                v = sub[-1] - sub[0]
                nm, _, _ = seg_class(v / (np.linalg.norm(v) or 1), arclen(sub), size)
            elif nm == "提":
                bad += 0.5 * infos[g[0]][2]  # 提 与 反向的撇 同向，偏向撇
        else:
            nm = COMPOUND.get(names, "+".join(names))
        st = Stroke(pts=sub, name=nm)
        st.corners = [tuple(pts[segs[j][0]]) for j in g[1:]]
        out.append(st)
        bad += sum(infos[j][2] for j in g if not infos[j][1])
    return out, (len(out), bad)


def cyclic_corners(pts, w, turn=50):
    """闭环上找拐角（首尾相接）。"""
    P = np.asarray(pts[:-1], float)
    n = len(P)
    k = max(3, int(2.0 * w))
    if n < 3 * k:
        return []
    tv = np.zeros(n)
    for i in range(n):
        u = P[i] - P[(i - k) % n]
        v = P[(i + k) % n] - P[i]
        nu, nv = np.linalg.norm(u), np.linalg.norm(v)
        if nu and nv:
            tv[i] = ang_between(u / nu, v / nv)
    cs = []
    for i in np.argsort(-tv):
        if tv[i] < turn:
            break
        if all(min(abs(i - j), n - abs(i - j)) > k for j in cs):
            cs.append(int(i))
    return sorted(cs)


def orient_and_name(pts, w, size, in_loop, free=(True, True)):
    """pts 一条连笔（可能含多段，或闭环）。试两种走向（闭环还试各拐角起头），取笔数最少、走向最顺的切法。"""
    pts = np.asarray(pts, float)
    closed = len(pts) > 3 * w and np.linalg.norm(pts[0] - pts[-1]) < 1.2 * w
    cands = []
    if closed:
        P = pts[:-1]
        cs = cyclic_corners(pts, w)
        if not cs:
            cs = [0]
        for c0 in cs:
            for rev in (False, True):
                Q = np.roll(P, -c0, axis=0)
                Q = np.vstack([Q, Q[:1]])
                cuts = [(c - c0) % len(P) for c in cs if c != c0]
                if rev:
                    Q = Q[::-1]
                    cuts = [len(Q) - 1 - c for c in cuts]
                cands.append(_group(Q, sorted(cuts), w, size, True, False))
    else:
        cuts = split_corners(pts, w)
        for rev in (False, True):
            Q = pts[::-1] if rev else pts
            cc = sorted(len(pts) - 1 - c for c in cuts) if rev else cuts
            cands.append(_group(Q, cc, w, size, in_loop, free[0] if rev else free[1]))
    return min(cands, key=lambda t: t[1])[0]


# ---------------------------------------------------------------- 点（团块）

DOT_AREA = 0.9      # 残墨团块面积下限，单位 w²
DOT_END_GAP = 1.2   # 离已有笔画端点至少几个 w（排除横末三角、笔头顿笔）


def find_dots(ink, strokes, w, size):
    """骨架法会把点当毛刺剪掉或嫌太短丢掉。这里用「残墨」找点：
    已有笔画按笔宽画回去，剩下没被解释的墨团，够大、够圆、又不贴在笔画端点上的，算一个点。"""
    drawn = np.zeros_like(ink)
    t = max(2, int(round(1.25 * w)))
    for s in strokes:
        p = np.round(s.pts[:, ::-1]).astype(np.int32)
        cv2.polylines(drawn, [p], False, 1, thickness=t)
    res = (ink > 0) & (drawn == 0)
    k = max(1, int(round(0.25 * w)))
    res = cv2.morphologyEx(res.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(res, 8)
    ends = [np.array(s.start) for s in strokes] + [np.array(s.end) for s in strokes]
    out = []
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        bw, bh = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if area < DOT_AREA * w * w:
            continue
        if max(bw, bh) > 0.3 * size or max(bw, bh) > 3.5 * min(bw, bh):
            continue  # 太长：漏掉的整笔，不是点
        c = np.array([cen[i][1], cen[i][0]])
        if ends and min(np.linalg.norm(c - e) for e in ends) < DOT_END_GAP * w:
            continue
        ys, xs = np.nonzero(lab == i)
        st_ = Stroke(pts=np.array([[ys.min(), xs.min()], c, [ys.max(), xs.max()]], float), name="点")
        st_.start = (float(ys.min()), float(xs.min()))
        st_.end = (float(ys.max()), float(xs.max()))
        out.append(st_)
    return out


# ---------------------------------------------------------------- 主流程

def extract(gray: np.ndarray, params: "SkelParams | None" = None):
    """小图先放大到字身约 200px 再做，坐标再缩回原图。"""
    ink0 = binarize(gray)
    ys, xs = np.nonzero(ink0)
    size0 = float(max(np.ptp(ys), np.ptp(xs))) if len(ys) else float(max(gray.shape))
    params = params or SkelParams()
    f = 1.0 if size0 >= params.upscale_below else params.upscale_to / max(size0, 1)
    if f == 1.0:
        return _extract(gray)
    big = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    strokes, info = _extract(big)
    for s in strokes:
        s.pts = s.pts / f
        s.start = (s.start[0] / f, s.start[1] / f)
        s.end = (s.end[0] / f, s.end[1] / f)
        s.corners = [(c[0] / f, c[1] / f) for c in s.corners]
    info["w"] /= f
    info["scale"] = f
    return strokes, info


def _extract(gray: np.ndarray):
    ink = binarize(gray)
    ys, xs = np.nonzero(ink)
    size = float(max(np.ptp(ys), np.ptp(xs))) if len(ys) else float(max(gray.shape))
    sk = thin(ink)
    w = stroke_width(ink, sk)
    sk = prune_spurs(sk, maxlen=max(4, 2.2 * w, 0.08 * size))
    nodes, edges = build_graph(sk)
    edges = [e for e in edges if not (e[0] == e[1] and arclen(e[2]) < 2.5 * w)]

    # 交叉点近邻合并：两交叉点之间很短的边收成一点
    deg: dict = {}
    for a, b, p in edges:  # 度（自环算两次，同 networkx）
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    uf = {n: n for n in nodes}

    def find(x):
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    short = set()
    for i, (a, b, p) in enumerate(edges):
        if a != b and deg.get(a, 0) >= 3 and deg.get(b, 0) >= 3 and arclen(p) < 1.3 * w:
            uf[find(a)] = find(b)
            short.add(i)
    ends = {}  # 合并后节点 -> [(edge_i, 是否从该节点出发)]
    for i, (a, b, p) in enumerate(edges):
        if i in short:
            continue
        ends.setdefault(find(a), []).append((i, True))
        ends.setdefault(find(b), []).append((i, False))

    def edir(i, from_start):
        p = edges[i][2]
        return out_dir(p if from_start else p[::-1], w)

    # 交叉点处配对：顺势穿过（出向夹角接近 180°）
    pair = {}
    for n, lst in ends.items():
        if len(lst) < 3:
            if len(lst) == 2 and lst[0][0] != lst[1][0]:
                # 度为 2 的「节点」（短边收缩后剩下）直接接上
                pair[lst[0]] = lst[1]
                pair[lst[1]] = lst[0]
            continue
        cand = []
        for x in range(len(lst)):
            for y in range(x + 1, len(lst)):
                if lst[x][0] == lst[y][0]:
                    continue
                dev = 180 - ang_between(edir(*lst[x]), edir(*lst[y]))
                cand.append((dev, x, y))
        used = set()
        for dev, x, y in sorted(cand):
            if dev > 40 or x in used or y in used:
                continue
            used |= {x, y}
            pair[lst[x]] = lst[y]
            pair[lst[y]] = lst[x]
        # 拐角落在交叉点上（肩部有刻痕/顿笔残枝）：剩下的「向左来的横」与「向下去的竖/撇」接成横折
        free_ = [x for x in range(len(lst)) if x not in used]
        if len(free_) >= 2:
            dirs = {x: edir(*lst[x]) for x in free_}
            th = {x: math.degrees(math.atan2(-dirs[x][0], dirs[x][1])) for x in free_}
            left = [x for x in free_ if abs(abs(th[x]) - 180) < 25]
            down = [x for x in free_ if -125 < th[x] < -65]
            right = [x for x in free_ if abs(th[x]) < 25 and arclen(edges[lst[x][0]][2]) > 2.5 * w]
            if len(left) == 1 and len(down) == 1 and not right and lst[left[0]][0] != lst[down[0]][0]:
                a_, b_ = lst[left[0]], lst[down[0]]
                pair[a_] = b_
                pair[b_] = a_

    # 哪些边在环上（封闭框）
    adj: dict = {}
    for i, (a, b, p) in enumerate(edges):
        if i not in short:
            adj.setdefault(find(a), []).append((find(b), i))
            adj.setdefault(find(b), []).append((find(a), i))
    on_cycle = set()
    for i, (a, b, p) in enumerate(edges):
        if i in short:
            continue
        fa, fb = find(a), find(b)
        if fa == fb:
            on_cycle.add(i)
            continue
        if _has_path(adj, fa, fb, i):
            on_cycle.add(i)

    # 串成连笔
    done = set()
    chains = []
    for i in range(len(edges)):
        if i in short or i in done:
            continue
        # 往「起点端」回溯到链头
        cur, cur_from_start = i, True  # 站在边 i 的起点端
        seen = {i}
        while (cur, cur_from_start) in pair:
            j, js = pair[(cur, cur_from_start)]
            if j in seen:
                break
            seen.add(j)
            cur, cur_from_start = j, not js
        # 现在 (cur, cur_from_start) 是链头那一端；沿链走
        seq = []
        e, at_start = cur, cur_from_start
        while True:
            if e in done:
                break
            done.add(e)
            p = edges[e][2]
            seq.append(p if at_start else p[::-1])
            other = (e, not at_start)
            if other not in pair:
                break
            j, js = pair[other]
            e, at_start = j, js
        pts = []
        for p in seq:
            pts.extend(p if not pts else p[1:])
        loop = any(k in on_cycle for k in seen | {e})
        # 链两头是否悬空（节点只连这一条边）
        def is_free(edge, at_s):
            a_, b_, _ = edges[edge]
            n_ = find(a_ if at_s else b_)
            return len(ends.get(n_, [])) == 1
        f0 = is_free(cur, cur_from_start)
        f1 = is_free(e, not at_start)
        chains.append((np.asarray(pts, float), loop, (f0, f1)))

    strokes = []
    for pts, loop, free in chains:
        if len(pts) < 2 or arclen(pts) < 0.8 * w:
            continue
        for st in orient_and_name(pts, w, size, loop, free):
            if arclen(st.pts) < 1.0 * w:
                continue
            # 起止外推到墨迹边缘
            p0, p1 = st.pts[0], st.pts[-1]
            d0 = -out_dir(st.pts, w)
            d1 = -out_dir(st.pts[::-1], w)
            st.start = extend_tip(ink, p0, d0, 1.2 * w)
            st.end = extend_tip(ink, p1, d1, 1.2 * w)
            strokes.append(st)
    # 去掉笔头/横末三角之类的小碎笔：很短、且一端贴着别的笔的端点或笔身
    def near_other(st):
        for o in strokes:
            if o is st:
                continue
            d = np.min(np.linalg.norm(o.pts[:, None, :] - np.array([st.pts[0], st.pts[-1]])[None], axis=2))
            if d < 1.6 * w:
                return True
        return False
    strokes = [s for s in strokes if not (arclen(s.pts) < max(2.6 * w, 0.11 * size) and near_other(s))]
    # 粗排书写顺序：先上后下、先左后右
    strokes.sort(key=lambda s: (round(s.start[0] / (0.12 * size)), s.start[1]))
    strokes += find_dots(ink, strokes, w, size)
    strokes.sort(key=lambda s: (round(s.start[0] / (0.12 * size)), s.start[1]))
    info = dict(w=w, size=size, ink=ink, skel=sk)
    return strokes, info
