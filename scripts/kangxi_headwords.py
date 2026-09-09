# -*- coding: utf-8 -*-
"""康熙字典（CADAL 12 冊 DjVu，中華書局影印同文書局本）字頭切圖。

页码体系（2026-09-07 实测，重要）：
  * DjVu 页 p → 印刷页码（页边栏汉字数字）= p + OFFSET[vol]，每册常数（12 册已全部人工核过）。
  * 但本影印本的印刷页码 ≠ Unihan / cjkvi kx2ucs 用的中華書局本页码！两者只在 人部（91）附近重合，
    之后本书页数越来越多：口部 177 vs kx 171，皮部 875 vs kx 790，艸部 1133 vs kx 1017，
    見部 1261 vs kx 1133，隹部 ~1531 vs kx 1364，馬部 1601 vs kx 1433（差值随页码近似线性 ≈ -10%）。
    所以「按页码查 kx2ucs 数字头」不可行；对齐改为按部首的序列对齐：
    ① 部首标题列（「X部」独占一列）把整册切成部，各部检测数与 kx2ucs 各部字数做 DP 对应（允许漏/多标题、
       跳过卷首目录页的假标题）。跑之前先剔两类会毁掉切段的页（见 body_pages / drop_front_matter）：
       每册开头的「集目」页（整版目录列 → 几十个假标题段；v3 不剔就只有 0.7% 赋字率）、
       以及 v12 末尾的 補遺/備考（印 1719-1826，每页 10+ 个标题列，kx2ucs 侧对应条目也已剔除）。
       DP 的代价除字数差外还有一项页码一致性罚（PAGE_COST_W）：光比字数是欠定的，各部字数分布相似，
       整体前后滑一两个部总代价几乎不变（v3 实测会滑到 大部，段大小全对得上但 embedding 全对不上）；
    ② 部内用字形识别引导的单调对齐（recog_align）：每个字头切图的 glyph-CNN
       embedding 与该部每个 kx2ucs 字（含 * 附列古文，它们也印成大字）的字体模板 embedding 算余弦，
       逐行 z 分标准化后做 Needleman–Wunsch（跳过检测项/跳过 kx 项各罚 0.45），相似度 ≥τ(0.55) 且
       前后邻居也对上（或更高相似度）才赋字；其余切图存为 unk。
    实测（2026-09-07，vol 1 pp84-186 / vol 9 全册，40 例人工抽检无标签错误）：见 run --dry 输出与 probe/mosaic_v*.png。
    旧的「带圈畫数分组 + 数量相等赋字」思路已弃用（圈的识别率不够，且未编码古文让组数对不上）。

版式（实测）：一 DjVu 页 = 一半叶，2737×3963。版框内 16 列，列距 ≈140px，列间**没有**竖线；
  版框位置随左右页交替（页码在左时框约 x 270-2550，页码在右时约 190-2445），框线淡、常断。
  字头是占满列宽的大字（~100-135px，笔画比小字粗 1.2-1.8 倍），注文小字（~55-65px）双行排在列的左右两半，
  中间留白道。部首起始处「X部」独占一列（新集另有「康熙字典」「子集中」列）。
  非字头的大号标记：带圈畫数 ㊀㊁…（细环 + 稀疏数字）、圈内「增」、方框「增」。
  字头后常接小字「古文」再接大字古文（kx2ucs 里带 *）；未编码的古文不在 kx2ucs 里 → 检测数略多于 kx2ucs。

检测（detect_headwords）：去长直线 → 自相关求列距、宽连通块投票求列相位 → 逐列切墨带 →
  先认标记（逐行左右墨端拟合圆/矩形）→ 大字判定：有笔画横贯列中线；或 門/非/刀 类中线无墨时看两半
  是否都在行界处分开（双行小字）+ 与本页可靠大字/小字的笔画粗细对比 → 碎片合并（二、六、艹字头）→
  标题列（无注文、≥2 个高字或全在列上部）。单页 0.3s。实测（8 测试页人工核）：漏检 ~3-6%
  （艹/竹 字头分离、走部两半都分块的字、淡墨页），误检 ~1-2%（粘连的双行小字、未认出的圈）。

用法：
    python scripts/kangxi_headwords.py detect --vol 1 --pages 100,150 --debug   # 单页调试，出可视化 probe/detect/
    python scripts/kangxi_headwords.py calib --vol 12 --pages 1-231             # 页边栏拼图（人工读页码定 OFFSET）+ 对齐试算
    python scripts/kangxi_headwords.py run --vol 1 --pages all --dry --mosaic 40   # 只对齐不切图（报表进 probe/dry/，抽检拼图 probe/mosaic_v01.png）
    python scripts/kangxi_headwords.py run --vol 1-12                              # 全量切图 → D:/data/glyph-sources/kangxi/crops
产物：
    crops/KX<page>.<pos>_<char>.png     赋了字的字头灰度图（含 8px 边），page.pos 为 kx2ucs 编号
    crops/unk/v<vol>_p<page>_<n>_unk.png 未赋字的字头切图
    crops/manifest.tsv                  vol, djvu_page, printed_page, n_detected, n_circles, n_heading_cols
    crops/sections.tsv                  vol, radical, (cadal_pages), n_detected, n_expected, n_matched, mean_sim, n_lowsim
依赖：config/kangxi/kx2ucs.txt；Unihan.zip（kRSUnicode，repo 的 config/variants/cache/Unihan.zip 或 D:/data/glyph-sources/kangxi/Unihan.zip）；
      字形 CNN checkpoint cache/glyph_cnn/best.pt（缺则退化为 HOG）与 fonts/（iming, jigmo）。
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

DDJVU = r"C:\Program Files (x86)\DjVuLibre\ddjvu.exe"
ROOT = Path("D:/data/glyph-sources/kangxi")
CADAL = ROOT / "cadal"
CROPS = ROOT / "crops"
KX2UCS = Path("config/kangxi/kx2ucs.txt")
W, H = 2737, 3963

# 印刷页码 = djvu 页 + OFFSET[vol]（2026-09-07 人工核：每册 5 个采样页全部一致）
OFFSET = {1: -9, 2: 173, 3: 293, 4: 403, 5: 529, 6: 657, 7: 795, 8: 967, 9: 1127, 10: 1257, 11: 1441, 12: 1595}
NPAGES = {1: 186, 2: 124, 3: 114, 4: 130, 5: 132, 6: 141, 7: 173, 8: 163, 9: 134, 10: 187, 11: 158, 12: 231}


def load_kx2ucs():
    """{kx_page: [char, ...]} 只取真字头（不含 `*` 附列古文）。"""
    per = collections.defaultdict(list)
    for l in KX2UCS.read_text(encoding="utf-8").splitlines():
        if l.startswith("#") or not l.strip():
            continue
        parts = l.split("\t")
        m = re.match(r"KX(\d{4})\.(\d{3})$", parts[0])
        if not m or len(parts) < 2:
            continue
        ch = parts[1]
        if ch.endswith("*"):
            continue
        per[int(m.group(1))].append((int(m.group(2)), ch))
    return {p: [c for _, c in sorted(v)] for p, v in per.items()}


def render(vol: int, page: int) -> np.ndarray:
    out = ROOT / "tmp" / f"v{vol:02d}_p{page:04d}.pgm"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        subprocess.run([DDJVU, f"-page={page}", "-format=pgm", f"-size={W}x{H}",
                        str(CADAL / f"cadal_v{vol:02d}.djvu"), str(out)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    img = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
    os.remove(out)
    return img


def _remove_rules(b: np.ndarray) -> np.ndarray:
    """去掉版框等长直线（长 ≥300px 的横/竖线），字的笔画都短于这个长度。"""
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 300))
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (300, 1))
    lines = cv2.morphologyEx(b, cv2.MORPH_OPEN, kv) | cv2.morphologyEx(b, cv2.MORPH_OPEN, kh)
    lines = cv2.dilate(lines, np.ones((5, 5), np.uint8))
    return b & (1 - lines)


MARKS = ("circle", "zeng", "box")   # 非字头的大号标记种类
FRAME_W = 2265   # 版框内宽（左右竖线间距，各页 2240-2290）


def _frame_x(b: np.ndarray):
    """版框左右竖线 x。版框位置随左右页交替：页码在左的页约 (270, 2550)，页码在右的页约 (190, 2445)。
    竖线常常很淡/断续，阈值放低；只找到一边时用 FRAME_W 推另一边；都没找到时按页边栏（页码所在侧）判定。"""
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 301))
    vp = cv2.morphologyEx(b, cv2.MORPH_OPEN, kv).sum(0)

    def best(lo, hi):
        seg = vp[lo:hi]
        return (lo + int(np.argmax(seg))) if seg.max() > 150 else None
    left, right = best(120, 420), best(2300, 2650)
    if left is not None and right is not None and abs((right - left) - FRAME_W) > 120:
        # 两条线间距不对（某侧抓到了别的长线）：信长的那条
        if vp[left] >= vp[right]:
            right = None
        else:
            left = None
    if left is None and right is None:
        margin_left = b[600:3400, 60:170].sum()
        margin_right = b[600:3400, 2600:2710].sum()
        return (268, 268 + FRAME_W) if margin_left >= margin_right else (2445 - FRAME_W, 2445)
    if left is None:
        left = right - FRAME_W
    if right is None:
        right = left + FRAME_W
    return int(left), int(right)


def _bands(rows: np.ndarray, thr: int, bridge: int = 2):
    """把行墨量序列切成墨带 [(y0,y1)...]：连续 ≥thr 的行，允许 ≤bridge 行的空隙。"""
    ink = rows >= thr
    out = []
    i, n = 0, len(ink)
    while i < n:
        if not ink[i]:
            i += 1
            continue
        j = i
        while j < n and (ink[j] or ink[j + 1:j + 1 + bridge].any()):
            j += 1
        out.append((i, j))
        i = j
    return out


def _fit_circle(P: np.ndarray):
    """代数最小二乘拟合圆，迭代 3 次只用内点重拟合（圈内「增」突出圈外的笔画端点是离群点）。
    返回 (cx, cy, r, inlier_mask, P) 或 None。"""
    sel = np.ones(len(P), bool)
    for _ in range(3):
        Q = P[sel]
        if len(Q) < 20:
            return None
        A = np.c_[2 * Q[:, 0], 2 * Q[:, 1], np.ones(len(Q))]
        try:
            (a, b, c), *_ = np.linalg.lstsq(A, (Q ** 2).sum(1), rcond=None)
        except np.linalg.LinAlgError:
            return None
        rr = np.sqrt(max(c + a * a + b * b, 1e-6))
        d = np.abs(np.hypot(P[:, 0] - a, P[:, 1] - b) - rr)
        sel = d <= 6
    return a, b, rr, d <= 5, P


def _is_mark(seg: np.ndarray, cc: int) -> str | None:
    """墨带是否是「非字头的大号标记」：带圈畫数（㊀㊁…）、圈内「增」、方框「增」。
    用逐行左右墨端的轮廓：圆环 → 行宽随行号呈半圆曲线；方框 → 行宽恒定、首末行是长横线、
    框线细（≤5.5px）且框本身是空心连通块（框内的字不与框相连；日/田/國 之类内部笔画连着外框）。
    环上可以有缺口（连通块碎成几段也不影响）。返回 'circle'/'box'/None。"""
    h, w = seg.shape
    s0 = seg > 0
    rows0 = np.where(s0.any(1))[0]
    if len(rows0) < 80:
        return None
    # 以各行墨中点的中位数为中心（列中线估计可能偏几十像素；邻列突入的墨也不影响中位数）
    cx = int(np.median([(np.where(s0[y])[0][0] + np.where(s0[y])[0][-1]) / 2 for y in rows0]))
    lo, hi = max(0, cx - 62), min(w, cx + 62)
    s = seg[:, lo:hi] > 0
    rows = np.where(s.any(1))[0]
    if len(rows) < 60 or len(rows) < 0.8 * h:
        return None
    L, R, TL, TR = [], [], [], []
    for y in rows:
        xs = np.where(s[y])[0]
        l, r = xs[0], xs[-1]
        L.append(l)
        R.append(r)
        t = 0
        while l + t < s.shape[1] and s[y, l + t]:
            t += 1
        TL.append(t)
        t = 0
        while r - t >= 0 and s[y, r - t]:
            t += 1
        TR.append(t)
    W = np.array(R) - np.array(L) + 1
    n = len(rows)
    bw = float(np.median(W[int(n * 0.3):int(n * 0.7)]))
    if bw < 80:
        return None
    thick = float(np.median(TL + TR))
    cy = (rows[0] + rows[-1]) / 2
    rad = bw / 2
    ideal = np.array([2 * np.sqrt(max(0.0, rad * rad - (y - cy) ** 2)) for y in rows])
    def circle_kind(cx0, cy0, rr):
        """环内靠环处 [0.76r, 0.9r] 墨很少（数字/增在更里面，双行小字块则整片有墨）；再按圈内墨密度分 畫数数字 / 增。"""
        yy, xx = np.mgrid[0:s.shape[0], 0:s.shape[1]]
        d2 = (xx - cx0) ** 2 + (yy - cy0) ** 2
        ann = (d2 >= (0.76 * rr) ** 2) & (d2 <= (0.9 * rr) ** 2)
        if not ann.any() or float(s[ann].mean()) > 0.22:   # 双行小字块整片有墨（~0.3）；增 的笔画会碰到环（~0.1-0.2）
            return None
        inside = d2 <= (0.72 * rr) ** 2
        dens = float(s[inside].mean()) if inside.any() else 0.0
        return "circle" if dens <= 0.40 else "zeng"   # 数字 ≤0.34，增 ≥0.45
    if np.mean(np.abs(W - ideal) <= 12) >= 0.8 and thick <= 6:
        r = circle_kind((np.median(L) + np.median(R)) / 2, cy, rad)
        if r:
            return r
    # 圈内的字（如「增」）可能突出圈外、圈线有缺口 → 用细的左右墨端点拟合圆（代数最小二乘），看内点比例
    pts = [(L[i], rows[i]) for i in range(n) if TL[i] <= 4] + [(R[i], rows[i]) for i in range(n) if TR[i] <= 4]
    if len(pts) >= 40:
        fit = _fit_circle(np.array(pts, float))
        if fit is not None:
            a, b, rr, inl, P = fit
            ang = np.degrees(np.arctan2(P[inl, 1] - b, P[inl, 0] - a))
            # 内点绕圆至少 240°（入/八 等两撇拟合不出整圈；环的上下缺口会少 2-4 格）；
            # 且各行的左右墨端间距要符合该圆的弦长（双行小字块行宽恒定，对不上圆）
            chord = 2 * np.sqrt(np.maximum(0.0, rr * rr - (rows - b) ** 2))
            if (42 <= rr <= 68 and inl.sum() >= 50 and inl.mean() >= 0.6
                    and len(set((ang // 30).astype(int))) >= 8 and np.mean(np.abs(W - chord) <= 12) >= 0.7):
                r = circle_kind(a, b, rr)
                if r:
                    return r
    if np.mean(np.abs(W - bw) <= 8) >= 0.8 and thick <= 5.5 and W[0] >= 0.7 * bw and W[-1] >= 0.7 * bw:
        # 框须是空心的独立连通块
        nlab, lab, st, _ = cv2.connectedComponentsWithStats(s.astype(np.uint8), connectivity=8)
        k = lab[rows[0], L[0]]
        if k > 0 and st[k, 4] <= 0.18 * st[k, 2] * st[k, 3] and st[k, 3] >= 0.9 * n:
            return "box"
    return None


def _half_chunks(hs: np.ndarray):
    """半列（列中线一侧）里墨在竖向上的块：[(y0,y1), ...]（≥2 行空白为界）。"""
    if hs.shape[1] <= 0:
        return []
    r = hs.sum(1) >= 2
    out = []
    i, n = 0, len(r)
    while i < n:
        if r[i]:
            j = i
            while j < n and (r[j] or (j + 1 < n and r[j + 1])):
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return [(a, b) for a, b in out if b - a >= 6]


def _box_like(hs: np.ndarray, chunk_h: int) -> bool:
    """半列里是否有注文方框：两条 ≤4px 细的、几乎贯通块高的竖线，相距 ≥35px。
    （大字如 門 的一扇只有一条粗竖，不满足。）"""
    if hs.shape[1] < 30:
        return False
    tall = hs.sum(0) >= 0.75 * chunk_h
    runs = []
    i, n = 0, len(tall)
    while i < n:
        if tall[i]:
            j = i
            while j < n and tall[j]:
                j += 1
            if j - i <= 4:
                runs.append((i + j) / 2)
            i = j
        else:
            i += 1
    return len(runs) >= 2 and (runs[-1] - runs[0]) >= 35


def _half_split(hs: np.ndarray, waist_thr: float):
    """半列的墨是否像「两个小字上下排」：(是否, 分界 y 或 None)。
    情形：两块以上（各 ≥30 高）；单块但中部有细腰（某行墨 ≤ waist_thr，小字粘连处）；细线方框。"""
    ch = _half_chunks(hs)
    if len(ch) >= 2:
        big = [(a, b) for a, b in ch if b - a >= 30]
        if len(big) >= 2:
            # 取最大空隙
            gaps = [(big[i + 1][0] - big[i][1], (big[i][1] + big[i + 1][0]) / 2) for i in range(len(big) - 1)]
            g, y = max(gaps)
            return True, y
    if len(ch) >= 1:
        a, b = max(ch, key=lambda t: t[1] - t[0])
        if b - a >= 80:
            if _box_like(hs[a:b], b - a):
                return True, None
            r = hs[a + 15:b - 15].sum(1)
            if len(r) and r.min() <= waist_thr:
                return True, a + 15 + int(np.argmin(r))
    return False, None


def _features(seg: np.ndarray, cc: int, y0: int):
    """一个墨带（seg: 0/1，cc: 列中线在 seg 内的 x）的特征。"""
    h, w = seg.shape
    cols = seg.sum(0)
    xs = np.where(cols > 0)[0]
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    lo, hi = max(0, cc - 12), min(w, cc + 12)
    seg8 = np.ascontiguousarray(seg).astype(np.uint8) * 255
    dt = cv2.distanceTransform(seg8, cv2.DIST_L2, 5)
    v = dt[seg > 0]
    left, right = seg[:, :max(0, cc - 3)], seg[:, min(w, cc + 3):]
    return dict(
        y0=y0, y1=y0 + h, x0=x0, x1=x1, cc=cc, ccl=cc,
        cross=int((seg[:, lo:hi].mean(1) >= 0.9).sum()),   # 墨横跨列中线 ±12px（≥90% 像素，容忍笔画里的白点）的行数
        dt=float(v.mean()) if len(v) else 0.0,          # 平均距离变换 ≈ 笔画粗细/4
        left=left, right=right,
        seg8=seg8, kind="small")


def _column_bands(sub: np.ndarray, cc: int):
    """一列内的墨带及其特征。sub: 该列二值图(0/1)，cc: 列中线在 sub 内的 x。
    高 >160 的带（大字与注文粘连、或注文成串）先用 3×3 腐蚀后的图再切一次。"""
    h, w = sub.shape
    rows = sub.sum(1)
    out = []
    er = None
    for (a, b) in _bands(rows, 8):
        if b - a < 8 or sub[a:b].sum() == 0:
            continue
        parts = [(a, b)]
        if b - a > 160:
            if er is None:
                er = cv2.erode(sub.astype(np.uint8), np.ones((3, 3), np.uint8))
            sb = [(a + p, a + q) for p, q in _bands(er[a:b].sum(1), 5) if q - p >= 8]
            if len(sb) >= 2:
                # 用腐蚀图的切点回到原图切：每个子带向外扩到原图的空白行为止（最多 2 行）
                parts = []
                for p, q in sb:
                    p2, q2 = max(a, p - 2), min(b, q + 2)
                    parts.append((p2, q2))
        for p, q in parts:
            seg = sub[p:q]
            if seg.sum() == 0:
                continue
            out.append(_features(seg, cc, p))
    # 带圈畫数的环常有缺口而被切成 2-3 段：相邻带合起来高 85-135 且能认成标记的，合成一带
    i = 0
    while i < len(out):
        merged = False
        for k in (2, 3):
            if i + k > len(out):
                break
            grp = out[i:i + k]
            if any(grp[j + 1]["y0"] - grp[j]["y1"] > 25 for j in range(k - 1)):
                break
            y0, y1 = grp[0]["y0"], grp[-1]["y1"]
            if not (85 <= y1 - y0 <= 135):
                continue
            seg = sub[y0:y1]
            mk = _is_mark(np.ascontiguousarray(seg).astype(np.uint8) * 255, cc)
            if mk:
                nb = _features(seg, cc, y0)
                nb["premark"] = mk
                out[i:i + k] = [nb]
                merged = True
                break
        i += 1 if not merged else 1
    return out


def _classify(bd: dict, dt_small: float, dt_big: float):
    """给单个墨带定性：big（字头级大字）/ piece（大字碎片，如 二 的一横）/ small / circle / box。"""
    ht, wd = bd["y1"] - bd["y0"], bd["x1"] - bd["x0"]
    xc = (bd["x0"] + bd["x1"]) / 2
    ratio = bd["dt"] / dt_small      # 相对本页小字的笔画粗细，大字 ≈1.2-1.8，小字 ≈1±0.2
    bd["ratio"] = ratio
    kind = "small"
    if bd.get("premark"):
        bd["kind"] = bd["premark"]
        return
    if 70 <= ht <= 160 and wd >= 80:
        mk = _is_mark(bd["seg8"], bd["ccl"])   # 先认标记：带圈畫数的环很细，按粗细会被当成小字；环上下常有缺口，带会偏矮
        if mk:
            bd["kind"] = mk
            return
    if 88 <= ht <= 160 and wd >= 30:
        if bd["cross"] >= 8:
            kind = "big"             # 有笔画横贯列中线（双行小字之间是白道）
        elif wd < 70:
            if abs(xc - bd["cc"]) <= 15 and ratio >= 1.15:
                kind = "big"         # 窄而居中的高字（刂、丨、卜）；单行小字堆叠则偏在一侧
        elif ratio < 1.05:
            kind = "small"           # 比本页小字还细 → 注文
        else:
            # 門/非/北/艹字头 类中线无墨的大字 vs 双行小字粘连块。
            # 结构：小字块的两半都在行界处「分开」（两块 / 细腰 / 方框）且分界在带中段、两半大致对齐；
            #       艹/竹 字头的上部块只有 30-45 高（分界偏上），門 的两扇各自贯通、无腰。
            # 粗细：以本页可靠大字（cross≥8）与小字的 dt 中点为界，淡墨页两者接近时结构优先。
            waist_thr = max(2.0, 0.7 * (4 * dt_small - 2))
            ls, ly = _half_split(bd["left"], waist_thr)
            rs, ry = _half_split(bd["right"], waist_thr)
            mid_thr = (dt_small + dt_big) / 2
            if ls and rs:
                ys = [y for y in (ly, ry) if y is not None]
                aligned = len(ys) < 2 or abs(ys[0] - ys[1]) <= 25
                mid = all(0.25 * ht <= y <= 0.75 * ht for y in ys)
                if aligned and mid:
                    kind = "big" if bd["dt"] >= 0.95 * dt_big else "small"   # 走/林 类两半都分块、但笔画与可靠大字差不多粗
                else:
                    kind = "big" if bd["dt"] >= mid_thr else "small"
            elif ls or rs:
                y = ly if ls else ry
                if y is not None and not (0.3 * ht <= y <= 0.7 * ht):
                    kind = "big"     # 只有一半、且分界靠上/靠下 → 艹/竹 字头与字身的缝，不是小字行界
                else:
                    kind = "big" if bd["dt"] >= mid_thr else "small"
            else:
                kind = "big"
            bd["split"] = (ls, ly, rs, ry)
    elif ht < 88 and bd["cross"] >= 6 and ratio >= 1.25 and wd >= 60:
        kind = "piece"           # 大字碎片（二 的一横、六 的亠…）：粗且横贯中线；粘连的双行小字 ratio ≈1-1.2
    bd["kind"] = kind


def _merge_pieces(bands: list, mid_thr: float):
    """合并被横向空白切开的大字碎片（二、三、六、品、艹字头+字身…）：
    相邻(≤25px)两带合并后高 90-145、宽 ≥85、都居中，且其一是 piece/big，或两者都明显粗于小字且其一 ≤48 高
    （艹/竹/亠 等部件；两行注文各 ~55-65 高不会都满足）。每轮只合并「合起来最像一个大字（高≈118）」的一对，
    避免 艹 字头被并到上一行注文里。"""
    merged = list(bands)
    while True:
        cands = []
        for i in range(len(merged) - 1):
            a, b = merged[i], merged[i + 1]
            if a["kind"] in MARKS or b["kind"] in MARKS:
                continue
            gap = b["y0"] - a["y1"]
            tot = b["y1"] - a["y0"]
            ux0, ux1 = min(a["x0"], b["x0"]), max(a["x1"], b["x1"])
            cc = a["cc"]
            centered = abs((a["x0"] + a["x1"]) / 2 - cc) <= 25 and abs((b["x0"] + b["x1"]) / 2 - cc) <= 25
            strong = "piece" in (a["kind"], b["kind"]) or "big" in (a["kind"], b["kind"])
            thick = (a["dt"] >= mid_thr and b["dt"] >= mid_thr and (a["x1"] - a["x0"]) >= 60 and (b["x1"] - b["x0"]) >= 60
                     and min(a["y1"] - a["y0"], b["y1"] - b["y0"]) <= 48)
            if gap <= 25 and 90 <= tot <= 145 and ux1 - ux0 >= 85 and centered and (strong or thick):
                cands.append((abs(tot - 118), i))
        if not cands:
            break
        _, i = min(cands)
        a, b = merged[i], merged[i + 1]
        nb = dict(a)
        nb.update(y1=b["y1"], x0=min(a["x0"], b["x0"]), x1=max(a["x1"], b["x1"]),
                  kind="big" if b["y1"] - a["y0"] >= 88 else "piece",
                  cross=a["cross"] + b["cross"], ratio=max(a["ratio"], b["ratio"]),
                  dt=max(a["dt"], b["dt"]), seg8=None)
        merged[i:i + 2] = [nb]
    for bd in merged:
        if bd["kind"] == "piece":
            # 孤立的宽横（字头「一」）：宽 95-135、粗；其余碎片降为小字
            wd, ht = bd["x1"] - bd["x0"], bd["y1"] - bd["y0"]
            bd["kind"] = "big" if (95 <= wd <= 135 and bd["ratio"] >= 1.4 and 8 <= ht <= 30) else "small"
    return merged


def detect_headwords(gray: np.ndarray, debug_path: Path | None = None):
    """返回按阅读序（列右→左，列内上→下）排列的字头框 [(x0,y0,x1,y1), ...] 与 info。
    info: ncols, pitch, dt_small, markers（带圈畫数/方框增 标记框）, headings（部首/集名标题列里的大字框，不算字头）, bands。"""
    b = (gray < 140).astype(np.uint8)
    h, w = b.shape
    fx0, fx1 = _frame_x(b)
    bb = _remove_rules(b)
    Y0, Y1 = 300, min(h, 3700)
    bb[:Y0] = 0
    bb[Y1:] = 0
    bb[:, :fx0 + 4] = 0
    bb[:, fx1 - 3:] = 0
    info = {"ncols": 0, "pitch": 0, "dt_small": 0.0, "dt_big": 0.0, "markers": [], "headings": [], "bands": [],
            "box_cols": [], "heading_cols": [], "marker_cols": []}
    # 列距：竖向墨量剖面自相关；列相位：宽 ≥75 的连通块（大字或跨双行的墨）x 中心投票
    prof = bb.sum(0).astype(float)
    sm = np.convolve(prof, np.ones(9) / 9, "same")
    x = sm[fx0:fx1] - sm[fx0:fx1].mean()
    if not x.any():
        return [], info
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    pitch = int(np.argmax(ac[120:165]) + 120)
    n, lab, st, cen = cv2.connectedComponentsWithStats(bb, connectivity=8)
    votes = [cen[i][0] for i in range(1, n) if 75 <= st[i][2] <= 220 and st[i][3] <= 220]
    if len(votes) < 2:
        return [], info
    ph = (np.angle(np.sum(np.exp(2j * np.pi * np.array(votes) / pitch))) / (2 * np.pi) * pitch) % pitch
    centers = [c for c in np.arange(ph - 25 * pitch, ph + 25 * pitch, pitch) if fx0 + pitch * 0.3 < c < fx1 - pitch * 0.3]
    centers = sorted(centers, reverse=True)  # 右→左
    info["ncols"], info["pitch"] = len(centers), pitch
    # 第一遍：各列墨带 + 特征
    cols = []
    for ci, c in enumerate(centers):
        x0, x1 = int(round(c - pitch / 2)), int(round(c + pitch / 2))
        x0c = max(0, x0)
        sub = bb[:, x0c:x1]
        if sub.sum() < 50:
            cols.append([])
            continue
        # 细调列中线：该列竖向剖面在 c±20 内的最小值（双行小字之间的白道）
        cp = np.convolve(sub.sum(0).astype(float), np.ones(5) / 5, "same")
        cc0 = int(c - x0c)
        lo, hi = max(2, cc0 - 20), min(len(cp) - 2, cc0 + 20)
        cc = int(lo + np.argmin(cp[lo:hi])) if hi > lo else cc0
        bands = _column_bands(sub, cc)
        for bd in bands:
            bd["x0"] += x0c
            bd["x1"] += x0c
            bd["cc"] += x0c
            bd["col"] = ci
        cols.append(bands)
    # 本页小字笔画粗细基准：高 ≤72、宽 ≥90（双行小字一行）的带的 dt 中位数
    small_dts = [bd["dt"] for bands in cols for bd in bands if bd["y1"] - bd["y0"] <= 72 and bd["x1"] - bd["x0"] >= 90]
    dt_small = float(np.median(small_dts)) if len(small_dts) >= 10 else 1.7
    big_dts = [bd["dt"] for bands in cols for bd in bands if 95 <= bd["y1"] - bd["y0"] <= 160 and bd["cross"] >= 8]
    dt_big = float(np.median(big_dts)) if len(big_dts) >= 3 else 1.5 * dt_small
    info["dt_small"], info["dt_big"] = dt_small, dt_big
    boxes, markers, headings, all_bands = [], [], [], []
    box_cols, heading_cols, marker_cols = [], [], []
    for ci, bands in enumerate(cols):
        for bd in bands:
            _classify(bd, dt_small, dt_big)
        bands = _merge_pieces(bands, (dt_small + dt_big) / 2)
        for bd in bands:
            for k in ("seg8", "left", "right"):
                bd.pop(k, None)
        all_bands += bands
        bigs = [(bd["x0"], bd["y0"], bd["x1"], bd["y1"]) for bd in bands if bd["kind"] == "big"]
        # 注文行：高 30-80、中线无墨的双行或窄的单行
        smalls = [bd for bd in bands if bd["kind"] == "small" and 30 <= bd["y1"] - bd["y0"] <= 80
                  and (bd["cross"] == 0 or bd["x1"] - bd["x0"] <= 70)]
        # 标题字（康熙字典 / 子集中 / 人部）：高 ≥90 且居中的带，不论粗细（「部」有时被判小）
        tallish = [(bd["x0"], bd["y0"], bd["x1"], bd["y1"]) for bd in bands
                   if bd["kind"] in ("big", "small") and bd["y1"] - bd["y0"] >= 90 and bd["x1"] - bd["x0"] >= 60
                   and abs((bd["x0"] + bd["x1"]) / 2 - bd["cc"]) <= 20]
        mk = [bd for bd in bands if bd["kind"] in MARKS]
        markers += [(bd["x0"], bd["y0"], bd["x1"], bd["y1"], bd["kind"]) for bd in mk]
        marker_cols += [ci] * len(mk)
        # 标题列（康熙字典 / 子集中 / 人部 / 丶部）：没有注文；要么 ≥2 个高字，
        # 要么 2-5 个带全在列的上半部且至少一个高字（部首本身可能很矮：丶、丨、二、乙）
        nz = [bd for bd in bands if bd["y1"] - bd["y0"] >= 12 and bd["kind"] != "small" or
              (bd["kind"] == "small" and bd["y1"] - bd["y0"] >= 12)]
        top_only = nz and 2 <= len(nz) <= 5 and max(bd["y1"] for bd in nz) < Y0 + 0.45 * (Y1 - Y0) and len(tallish) >= 1
        if not smalls and (len(tallish) >= 2 or top_only):
            headings += tallish if len(tallish) >= 2 else [(bd["x0"], bd["y0"], bd["x1"], bd["y1"]) for bd in nz]
            heading_cols.append(ci)
        else:
            boxes += bigs
            box_cols += [ci] * len(bigs)
    info["markers"], info["headings"], info["bands"] = markers, headings, all_bands
    info["box_cols"], info["heading_cols"], info["marker_cols"] = box_cols, heading_cols, marker_cols
    if debug_path is not None:
        vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for c in centers:
            xx = int(round(c - pitch / 2))
            cv2.line(vis, (xx, Y0), (xx, Y1), (255, 0, 0), 2)
        if os.environ.get("KX_DEBUG_BANDS"):
            for bd in all_bands:
                if bd["kind"] == "small":
                    cv2.rectangle(vis, (bd["x0"], bd["y0"]), (bd["x1"], bd["y1"]), (0, 160, 0), 1)
                    cv2.putText(vis, f'{bd["y1"]-bd["y0"]}x{bd["x1"]-bd["x0"]} c{bd["cross"]} r{bd["ratio"]:.2f} {bd.get("split","")}',
                                (bd["x0"], bd["y0"] + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 0, 200), 1)
        for (x0, y0, x1, y1, k) in markers:
            cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 200, 200), 4)
        for (x0, y0, x1, y1) in headings:
            cv2.rectangle(vis, (x0, y0), (x1, y1), (200, 0, 200), 4)
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 0, 255), 5)
            cv2.putText(vis, str(i + 1), (x0, max(20, y0 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 160, 0), 4)
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        if os.environ.get("KX_DEBUG_BANDS"):
            cv2.imwrite(str(debug_path.with_name(debug_path.stem + "_full.png")), vis)
        s = 1300 / vis.shape[1]
        cv2.imwrite(str(debug_path), cv2.resize(vis, None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
    return boxes, info


def parse_pages(s: str, vol: int):
    if s == "all":
        return list(range(1, NPAGES[vol] + 1))
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def parse_vols(s: str):
    return parse_pages(s, 0) if ("-" in s or "," in s) else [int(s)]


def cmd_detect(a):
    kx = load_kx2ucs()
    for vol in parse_vols(a.vol):
        for p in parse_pages(a.pages, vol):
            g = render(vol, p)
            dbg = ROOT / "probe" / "detect" / f"v{vol:02d}_p{p:04d}.png" if a.debug else None
            boxes, info = detect_headwords(g, dbg)
            kxp = p + OFFSET[vol] if OFFSET.get(vol) is not None else None
            exp = len(kx.get(kxp, [])) if kxp else "?"
            marks = collections.Counter(m[4] for m in info["markers"])
            print(f"v{vol} p{p} printed{kxp}: detected {len(boxes)} (kx2ucs@printed {exp}, 仅供参考) "
                  f"ncols={info['ncols']} headings={len(info['headings'])} marks={dict(marks)}")


# ---------------------------------------------------------------------------------------------
# 与 kx2ucs 的对齐：部首标题列 → 部；带圈畫数 → 部内的畫数组；组内数量相等时按序赋字。
# ---------------------------------------------------------------------------------------------
RADICALS = ("一丨丶丿乙亅二亠人儿入八冂冖冫几凵刀力勹匕匚匸十卜卩厂厶又口囗土士夂夊夕大女子宀寸小尢尸屮山巛工己巾干幺广廴廾弋弓彐彡彳"
            "心戈戶手支攴文斗斤方无日曰月木欠止歹殳毋比毛氏气水火爪父爻爿片牙牛犬玄玉瓜瓦甘生用田疋疒癶白皮皿目矛矢石示禸禾穴立竹米糸缶网羊羽老而耒耳聿肉臣自至臼舌舛舟艮色艸"
            "虍虫血行衣襾見角言谷豆豕豸貝赤走足身車辛辰辵邑酉釆里金長門阜隶隹雨靑非面革韋韭音頁風飛食首香馬骨高髟鬥鬯鬲鬼魚鳥鹵鹿麥麻黃黍黑黹黽鼎鼓鼠鼻齊齒龍龜龠")
RADICAL_ALT = {"玄": "𤣥"}   # kx2ucs 里的写法
# kx2ucs 里 ≥ 这一页的是 補遺/備考（KX1545 起，从「一部」重排，6419 条），正文（子集～亥集）到 KX1538 龠部为止。
SUPPLEMENT_KX_PAGE = 1545
UNIHAN_ZIPS = [Path("config/variants/cache/Unihan.zip"), ROOT / "Unihan.zip"]


def load_krs():
    """{char: kRSUnicode 部外笔画数}。读 Unihan.zip 里的 Unihan_IRGSources.txt（kRSKangXi 在 Unicode 15.1 已删除，
    kRSUnicode 绝大多数与康熙归部/畫数一致，个别出入靠 kx2ucs 顺序 + 中值平滑消掉）。"""
    import zipfile
    for zp in UNIHAN_ZIPS:
        if zp.exists():
            break
    else:
        raise SystemExit(f"需要 Unihan.zip（放到 {UNIHAN_ZIPS[1]}）：https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip")
    out = {}
    with zipfile.ZipFile(zp) as z, z.open("Unihan_IRGSources.txt") as f:
        for raw in f:
            if b"\tkRSUnicode\t" not in raw:
                continue
            cp, _, v = raw.decode("utf-8").rstrip("\n").split("\t")
            out[chr(int(cp[2:], 16))] = int(v.split()[0].split(".")[1])
    return out


def kx_sections():
    """kx2ucs 按部首切成 214 段，每段再按（平滑后的）部外畫数切组。
    返回 [dict(radical, entries=[(page,pos,char,is_variant)...], groups=[[entry_idx...]...])]，按字典顺序。
    kx 页 ≥ SUPPLEMENT_KX_PAGE 的条目（補遺/備考）全部丢弃：它们从「一部」重新按部首排一遍，
    没有部首标题行可切，留着会全部堆进最后一个部（龠部本来只有 20 字，会变成 6436 字）。"""
    entries = []
    for l in KX2UCS.read_text(encoding="utf-8").splitlines():
        if l.startswith("#") or not l.strip():
            continue
        parts = l.split("\t")
        m = re.match(r"KX(\d{4})\.(\d{3})$", parts[0])
        if not m or len(parts) < 2:
            continue
        if int(m.group(1)) >= SUPPLEMENT_KX_PAGE:
            continue
        ch = parts[1].strip()
        entries.append((int(m.group(1)), int(m.group(2)), ch.rstrip("*"), ch.endswith("*")))
    entries.sort()
    krs = load_krs()
    starts = []
    i = 0
    for r in RADICALS:
        alt = (r, RADICAL_ALT.get(r))
        j = i
        while j < len(entries) and not (entries[j][2] in alt and not entries[j][3]):
            j += 1
        if j >= len(entries):
            starts.append(None)
            continue
        starts.append(j)
        i = j
    secs = []
    for k, r in enumerate(RADICALS):
        a = starts[k]
        if a is None:
            continue
        b = next((starts[m] for m in range(k + 1, len(RADICALS)) if starts[m] is not None), len(entries))
        ents = entries[a:b]
        # 每条的部外畫数：附列古文继承前一个正字头；查不到的继承前值
        raw = []
        prev = 0
        for (_, _, ch, var) in ents:
            v = prev if var else krs.get(ch, prev)
            raw.append(v)
            prev = v
        raw = np.array(raw, float)
        med = np.array([np.median(raw[max(0, t - 2):t + 3]) for t in range(len(raw))])
        mono = np.maximum.accumulate(med)
        groups, cur = [], None
        for t, v in enumerate(mono):
            if cur is None or v != cur:
                groups.append([t])
                cur = v
            else:
                groups[-1].append(t)
        secs.append(dict(radical=r, entries=ents, groups=groups))
    return secs


# 段对齐里页码一致性项的权重（每偏 10 个 kx 页罚这么多）。
# v3 实测：w≤0.10 时 DP 仍选错误的 大部 起点，w≥0.15 才翻到正确的 子部；取 0.3 留一倍余量。
# 偏 30 页（页码估计的正常误差）罚 0.9，压不过字数项；偏 200 页（滑掉两三个部）罚 6.0，足以排除。
PAGE_COST_W = 0.3

# CADAL 印刷页码 → kx2ucs 页码的近似换算（两套页码在 人部 91 附近重合，之后 CADAL 每页装得少、
# 页数多出约 10%；下面用实测锚点线性插值，只用来「把候选部首限制在一个宽窗口里」，不做精确对齐）。
PAGE_ANCHORS = [(75, 75), (91, 91), (177, 171), (299, 277), (333, 307), (395, 375),
                (875, 790), (1133, 1017), (1261, 1133), (1531, 1364), (1601, 1433), (1718, 1538)]
# (299,277)=子部起、(333,307)=山部起、(395,375)=心部起：都由 v3 跑出来的高置信段（sim>1.2、
# 绝大多数字都对上）反查，并与页图人工核对过。旧的 (297,286) 是错的——它说印 297 → kx 286，
# 可印 299 明明是 子部 起 = kx 277，页码更后 kx 反而更前，自相矛盾；这个错锚让 297-875 之间
# 整段偏高 +10~12 页，页码罚项会去反对本来正确的段对齐（v3 的 巛/工/幺/彐/彡 就是这样丢掉的）。
# 末锚点是正文（龠部）的终点：影印印刷页 1718 ↔ kx 1538。
# 旧值 (1826, 1631) 把 v12 的 補遺/備考 尾巴（印 1719-1826）也算进正文，
# 等于把 馬-龠 的内容摊到多出来的 108 页上，候选部首窗口和段对齐全被拉偏。


def printed_to_kx(printed: int) -> float:
    """印刷页码 → 估计的 kx2ucs 页码（分段线性；超出锚点范围按端点斜率外推）。"""
    xs = [a for a, _ in PAGE_ANCHORS]
    ys = [b for _, b in PAGE_ANCHORS]
    return float(np.interp(printed, xs, ys))


def candidate_radicals(secs, vol, pages, slack=45):
    """本册可能涉及的 kx 部首下标区间 [lo, hi)。
    只按页码粗筛（±slack 页的余量），把「按数量对齐」限制在正确的区域——否则各册字数分布相似，
    纯数量 DP 会把丑集（土/大/女部）错配到艸/虫部这类字数相近的区域，相似度全 ≈0。"""
    off = OFFSET.get(vol)
    if off is None or not pages:
        return 0, len(secs)
    lo_kx = printed_to_kx(pages[0] + off) - slack
    hi_kx = printed_to_kx(pages[-1] + off) + slack
    lo = hi = None
    for i, sec in enumerate(secs):
        first = sec["entries"][0][0]
        if lo is None and first >= lo_kx:
            lo = max(0, i - 1)
        if first <= hi_kx:
            hi = i + 1
    return (lo or 0), (hi or len(secs))


def _align_sizes(cs, ss, merge_pen=0.08, free_last=False, free_first=False, c_kx=None, s_kx=None, page_w=0.0):
    """把两串数量序列对齐：允许一边的 1 项对另一边连续多项（漏检/多检的标题或圈），也允许跳过 CADAL 侧的段。
    代价 = |Σc-Σs|/max(Σs,5) + |Σc-Σs|/40 + 每合并一项 merge_pen。返回 (总代价, [(ci_lo,ci_hi,sj_lo,sj_hi), ...])。
    free_first/free_last：kx 侧开头/结尾可以免费跳过任意多个部（本册从第几部开始、到第几部截断都是未知的），
    这样整册只跑一次 DP 就能定位起始部——早先「穷举起始部 × 部数」的写法在整册 60+ 段时要跑上亿次内循环，会挂住。

    c_kx/s_kx/page_w：页码一致性项（page_w>0 时启用）。c_kx[i] 是第 i 个 CADAL 段起始印刷页换算出的
    kx 页估计，s_kx[j] 是第 j 个 kx 部的起始页；每对上一段就加 page_w * |c_kx - s_kx| / 10。
    光靠字数对齐是欠定的——各部字数分布相似，DP 可以整体前后滑一两个部而总代价几乎不变
    （v3 实测：真起点是 子部 kx277，DP 却选了 大部 kx248，段大小全都对得上但 embedding 全对不上，
    赋字率 1%）。页码估计有 ±45 页误差，做不了硬约束，但足以把「滑掉两三个部」这种解排除掉。"""
    n, m = len(cs), len(ss)
    INF = 1e18
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    P = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    if free_first:
        for j in range(1, m + 1):
            D[0][j] = 0.0
            P[0][j] = (0, j - 1, "skipE")
    K = 6
    for i in range(n + 1):
        for j in range(m + 1):
            if D[i][j] >= INF:
                continue
            if i < n:   # 跳过一个 CADAL 段（卷首目录页之类的假标题列），罚 2 + 字数/60
                sk = 2.0 + cs[i] / 60
                if D[i][j] + sk < D[i + 1][j]:
                    D[i + 1][j] = D[i][j] + sk
                    P[i + 1][j] = (i, j, "skip")
            for di in range(1, K + 1):
                if i + di > n:
                    break
                for dj in range(1, K + 1):
                    if j + dj > m or (di > 1 and dj > 1):
                        break
                    c = sum(cs[i:i + di])
                    s_ = sum(ss[j:j + dj])
                    # 相对误差 + 绝对误差/40（大段差几十个字必须重罚，否则小部首的噪声会把整体错位一个部）
                    if free_last and i + di == n:   # 卷末被切断的段：只罚多不罚少
                        diff = max(0, c - s_)
                    else:
                        diff = abs(c - s_)
                    cost = diff / max(s_, 5) + diff / 40 + merge_pen * (di + dj - 2)
                    if page_w and c_kx is not None and s_kx is not None:
                        cost += page_w * abs(c_kx[i] - s_kx[j]) / 10.0
                    if D[i][j] + cost < D[i + di][j + dj]:
                        D[i + di][j + dj] = D[i][j] + cost
                        P[i + di][j + dj] = (i, j, "match")
    if free_last:
        j_best = min((jj for jj in range(m + 1) if D[n][jj] < INF), key=lambda jj: D[n][jj], default=m)
    else:
        j_best = m
    if D[n][j_best] >= INF:
        return INF, []
    pairs = []
    i, j = n, j_best
    while (i, j) != (0, 0):
        pi, pj, kind = P[i][j]
        if kind == "match":
            pairs.append((pi, i, pj, j))
        i, j = pi, pj
    return D[n][j_best], pairs[::-1]


KX_FIRST_PAGE = 75   # kx2ucs 收录的最小印刷页（此前是序/凡例/總目/等韻，全是大字无注文，会被误判成部首标题列）
# CADAL 影印本里 補遺/備考 的起始印刷页（v12 实测：1719 起每页都有 10+ 个标题列，之前 ≤1）。
SUPPLEMENT_PRINTED_PAGE = 1719
FRONT_MATTER_HEAD_COLS = 4   # 卷首集目页的判据：一页里 ≥ 这么多「标题列」
FRONT_MATTER_MAX_DJVU = 10   # 只在每册开头这么多页里找卷首集目


def body_pages(vol: int, pages):
    """滤掉正文之前的页：印刷页码 < KX_FIRST_PAGE 的一律不要。
    这些页（御製序、凡例、總目、等韻切音指南）满版大字、没有双行注文，每列都会被当成「部首标题列」，
    在整册对齐时制造上百个空段，既拖慢 DP 又把部首序列打乱。
    另外滤掉 補遺/備考（印刷页 ≥ SUPPLEMENT_PRINTED_PAGE，只有 v12 有）：kx2ucs 侧已经删掉这些条目，
    影印侧它们每页都有 10+ 个标题列，留着会把整册切成几百段，DP 无从对起。"""
    off = OFFSET.get(vol)
    if off is None:
        return list(pages)
    return [p for p in pages if KX_FIRST_PAGE <= p + off < SUPPLEMENT_PRINTED_PAGE]


def drop_front_matter(vol: int, pages, per_page: dict):
    """去掉每册开头的「集目」页（子集上/寅集上… 的部首目录）。
    这些页整版都是「X部 一畫」之类的目录列，检测器把几乎每一列都判成标题列
    （v3 印 297 页 14/16 列、印 298 页 10/16 列），于是流的最前面凭空多出几十个空段，
    _align_sizes 为了消化它们会把真正的头几个部（v3 的 山巛工己巾）吃掉，整册错位 → 赋字率 0.7%。
    判据：每册前 FRONT_MATTER_MAX_DJVU 页里，标题列数 ≥ FRONT_MATTER_HEAD_COLS 的那些页
    （及其之前的所有页）。真正的部首起始页只有 1-3 个标题列（v3 印 299 子部、v9 印 1133 艸部 都保住）。
    v1 没有集目页（它的卷首已被 KX_FIRST_PAGE 滤掉），cut=0 不动。"""
    ordered = sorted(pages)
    cut = 0
    for p in ordered[:FRONT_MATTER_MAX_DJVU]:
        if per_page.get(p, {}).get("heads", 0) >= FRONT_MATTER_HEAD_COLS:
            cut = p
    return [p for p in ordered if p > cut], cut


def scan_volume(vol, pages, log=print, keep_crops=False, man=None):
    """逐页检测，按阅读序汇成一个流：[dict(kind='g'|'c'|'h', page, col, y, box[, crop])]；标题列 → 'h'。"""
    stream, per_page = [], {}
    for p in pages:
        g = render(vol, p)
        boxes, info = detect_headwords(g)
        items = [dict(kind="h", page=p, col=hc, y=-1, box=None) for hc in info["heading_cols"]]
        items += [dict(kind="g", page=p, col=c, y=b[1], box=b) for b, c in zip(boxes, info["box_cols"])]
        if keep_crops:
            for it in items:
                if it["kind"] == "g":
                    x0, y0, x1, y1 = it["box"]
                    m = CROP_MARGIN
                    it["crop"] = g[max(0, y0 - m):y1 + m, max(0, x0 - m):x1 + m].copy()
        items += [dict(kind="c", page=p, col=c, y=m[1], box=m[:4]) for m, c in zip(info["markers"], info["marker_cols"]) if m[4] == "circle"]
        items.sort(key=lambda it: (it["col"], it["y"]))
        stream += items
        per_page[p] = dict(n=len(boxes), heads=len(info["heading_cols"]), circles=sum(1 for m in info["markers"] if m[4] == "circle"))
        if man is not None:   # 边扫边落盘，跑一半被中断也看得到进度
            man.write(f"{vol}\t{p}\t{p + OFFSET[vol]}\t{per_page[p]['n']}\t{per_page[p]['circles']}\t{per_page[p]['heads']}\n")
            man.flush()
        log(f"  v{vol} p{p}: {len(boxes)} glyphs, {per_page[p]['circles']} circles{', HEADING' if info['heading_cols'] else ''}")
        sys.stdout.flush()
    return stream, per_page


def align_volume(vol, stream, secs):
    """流 → 按标题切段 → 与 kx2ucs 部首段对齐（DP，允许漏/多标题）→ 段内按圈切组、与畫数组对齐。
    返回 (assignments=[(item, entry)], report=[dict])。"""
    # 1. 切段
    cad = [[]]
    heads = []
    for it in stream:
        if it["kind"] == "h":
            cad.append([])
            heads.append((it["page"], it["col"]))
        else:
            cad[-1].append(it)
    head_secs = cad[1:]           # 每段以一个标题开始
    sizes = [sum(1 for it in sec if it["kind"] == "g") for sec in head_secs]
    report = []
    if not head_secs:
        return [], [dict(level="volume", note="no heading found")]
    # 2. 首段部首 a 未知：穷举，取 DP 代价最小（最后一段可能被卷末切断，不计代价）
    ssizes = [len(s["entries"]) for s in secs]
    cost, pairs_all = _align_sizes(sizes, ssizes, free_last=True, free_first=True)
    a = pairs_all[0][2] if pairs_all else 0
    pairs = [(c0, c1, j0 - a, j1 - a) for (c0, c1, j0, j1) in pairs_all]
    report.append(dict(level="volume", first_radical=secs[a]["radical"], cost=round(cost, 3)))
    assignments = []
    for (ci0, ci1, sj0, sj1) in pairs:
        items = [it for k in range(ci0, ci1) for it in head_secs[k]]
        ksecs = secs[a + sj0:a + sj1]
        glyphs = [it for it in items if it["kind"] == "g"]
        exp_n = sum(len(s["entries"]) for s in ksecs)
        rad = "".join(s["radical"] for s in ksecs)
        pg0, pg1 = items[0]["page"] if items else None, items[-1]["page"] if items else None
        rep = dict(level="section", radical=rad, cadal_pages=(pg0, pg1), detected=len(glyphs), expected=exp_n,
                   n_head_cols=ci1 - ci0, n_kx_secs=sj1 - sj0, groups_ok=0, groups_bad=0)
        # 3. 段内分组：圈为界
        cgroups = [[]]
        for it in items:
            if it["kind"] == "c":
                cgroups.append([])
            else:
                cgroups[-1].append(it)
        cgroups = [g for g in cgroups if g] if any(cgroups) else []
        kgroups = []
        for s in ksecs:
            for grp in s["groups"]:
                kgroups.append([s["entries"][t] for t in grp])
        if not cgroups or not kgroups:
            report.append(rep)
            continue
        _, gpairs = _align_sizes([len(g) for g in cgroups], [len(g) for g in kgroups], merge_pen=0.05)
        for (gi0, gi1, gj0, gj1) in gpairs:
            gl = [it for k in range(gi0, gi1) for it in cgroups[k]]
            ke = [e for k in range(gj0, gj1) for e in kgroups[k]]
            if len(gl) == len(ke):
                assignments += list(zip(gl, ke))
                rep["groups_ok"] += 1
            else:
                rep["groups_bad"] += 1
                report.append(dict(level="group", radical=rad, cadal_pages=(gl[0]["page"], gl[-1]["page"]) if gl else None,
                                   detected=len(gl), expected=len(ke), expected_chars="".join(e[2] for e in ke)))
        report.append(rep)
    return assignments, report


# ---------------------------------------------------------------------------------------------
# 识别引导的序列对齐：字头切图的 CNN embedding vs 每个 kx2ucs 字的字体模板 embedding，
# 在部内做单调（Needleman–Wunsch）对齐，相似度够高且前后邻居也对上的才赋字。
# ---------------------------------------------------------------------------------------------
CACHE = ROOT / "cache"
CROP_MARGIN = 8
SKIP_D, SKIP_E, TAU, WILD = 0.45, 0.45, 0.55, 0.60   # 跳过检测项/跳过 kx 项 的罚分、接受阈值、通配项相似度


class Embedder:
    """字形向量：优先 open_guji_cv 的 glyph CNN（cache/glyph_cnn/best.pt，256-d embedding，GPU 批量），
    没有 checkpoint 时退化为 HOG。模板 = 该字在各字体（iming/jigmo）渲染图向量的均值，按字缓存到
    D:/data/glyph-sources/kangxi/cache/templates_<kind>.npz；渲染成豆腐块（字体缺字）的字体不计。"""

    def __init__(self):
        self.kind = "hog"
        self.cc = None
        try:
            from open_guji_cv.clustering.cnn_candidates import CnnCandidates, fingerprint
            cc = CnnCandidates()
            if cc._ensure():
                self.cc, self.kind, self.fp = cc, "cnn", fingerprint(cc.ckpt)
        except Exception as e:  # noqa: BLE001
            print(f"[embedder] CNN 不可用（{e}），用 HOG", file=sys.stderr)
        if self.cc is None:
            from open_guji_cv.clustering.features import HogFeature
            self.hog, self.fp = HogFeature(), "hog"
        self._tpl_file = CACHE / f"templates_{self.kind}_{self.fp}.npz"
        self._tpl = {}
        if self._tpl_file.exists():
            z = np.load(self._tpl_file, allow_pickle=False)
            self._tpl = dict(zip(z["chars"].tolist(), z["mat"]))
        self._tofu = None

    def embed(self, patches) -> np.ndarray:
        """[N,64,64] {0,1} → [N,d] 单位向量。"""
        P = np.asarray(patches, np.uint8)
        if len(P) == 0:
            return np.zeros((0, 256), np.float32)
        if self.cc is None:
            return self.hog.extract(P)
        import torch
        out = []
        with torch.no_grad():
            for k in range(0, len(P), 256):
                x = torch.tensor(P[k:k + 256, None].astype(np.float32), device=self.cc._dev)
                e, _, _ = self.cc._net(x)
                e = e / (e.norm(dim=1, keepdim=True) + 1e-9)
                out.append(e.cpu().numpy())
        return np.concatenate(out).astype(np.float32)

    def _fonts(self):
        from open_guji_cv.clustering.font_candidates import _font_files
        from open_guji_cv.clustering.synth import render_char
        if self._tofu is None:
            self._tofu = {}
            for fp in _font_files():
                try:
                    self._tofu[fp] = render_char("\u0378", fp, size=64)   # 未定义码位 → 该字体的豆腐块
                except Exception:  # noqa: BLE001
                    pass
        return self._tofu, render_char

    def templates(self, chars) -> dict:
        """{char: 单位向量 或 None}。None = 通配（无法渲染 / 非单字的 IDS 条目）。"""
        need = [c for c in set(chars) if c not in self._tpl]
        if need:
            tofu, render_char = self._fonts()
            names, ims, counts = [], [], []
            for ch in need:
                if len(ch) != 1:
                    self._tpl[ch] = None
                    continue
                k = 0
                for fp, ref in tofu.items():
                    try:
                        im = render_char(ch, fp, size=64)
                    except Exception:  # noqa: BLE001
                        continue
                    if im is None or not im.any() or (ref is not None and im.shape == ref.shape and np.array_equal(im, ref)):
                        continue
                    ims.append(im.astype(np.uint8))
                    k += 1
                names.append(ch)
                counts.append(k)
            if ims:
                E = self.embed(np.stack(ims))
            pos = 0
            for ch, k in zip(names, counts):
                if k == 0:
                    self._tpl[ch] = None
                else:
                    v = E[pos:pos + k].mean(0)
                    self._tpl[ch] = (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)
                pos += k
            CACHE.mkdir(parents=True, exist_ok=True)
            keep = [(c, v) for c, v in self._tpl.items() if v is not None]
            if keep:
                np.savez(self._tpl_file, chars=np.array([c for c, _ in keep]), mat=np.stack([v for _, v in keep]))
        return {c: self._tpl.get(c) for c in chars}


def _standardize(S: np.ndarray) -> np.ndarray:
    """余弦相似度非常压缩（同部内 mean≈0.94、std≈0.01，真匹配 0.97-0.995），改成逐行 z 分再线性映射：
    z 按去掉该行最高 3 个值后的均值/标准差算（避免真匹配抬高基线），score = (z-1)/4 → 真匹配约 0.6-1.2，随机项约 -0.25。"""
    n, m = S.shape
    if m < 6:
        mu, sd = S.mean(), max(S.std(), 0.008)
        return (((S - mu) / sd) - 1) / 4
    srt = np.sort(S, axis=1)[:, :-3]
    mu = srt.mean(1, keepdims=True)
    sd = np.maximum(srt.std(1, keepdims=True), 0.006)
    return (((S - mu) / sd) - 1) / 4


def _nw_align(S: np.ndarray, skip_d: float, skip_e: float, free_start=False, free_end=False):
    """单调对齐（Needleman–Wunsch）：S[i,j] 为检测项 i 与 kx 项 j 的相似度（匹配得分），
    跳过一个检测项罚 skip_d，跳过一个 kx 项罚 skip_e；free_start/free_end 允许 kx 侧开头/结尾免费跳过
    （卷首/卷末被切断的部）。返回按序的匹配对 [(i,j)...]。行内 numpy 向量化，1900×2000 约 1s。"""
    n, m = S.shape
    ar = np.arange(m + 1, dtype=np.float64)
    prev = np.zeros(m + 1) if free_start else -skip_e * ar
    ptr = np.zeros((n + 1, m + 1), np.int8)      # 0 对角(匹配) 1 上(跳检测项) 2 左(跳 kx 项)
    ptr[0, 1:] = 2
    for i in range(1, n + 1):
        diag = prev[:-1] + S[i - 1]
        up = prev[1:] - skip_d
        tmp = np.empty(m + 1)
        tmp[0] = prev[0] - skip_d
        tmp[1:] = np.maximum(diag, up)
        ptr[i, 0] = 1
        ptr[i, 1:] = np.where(diag >= up, 0, 1)
        cur = np.maximum.accumulate(tmp + skip_e * ar) - skip_e * ar
        ptr[i][cur > tmp + 1e-9] = 2
        prev = cur
    j = int(np.argmax(prev)) if free_end else m
    i = n
    pairs = []
    while i > 0 or j > 0:
        if i == 0 and free_start:
            break
        p = ptr[i, j]
        if p == 0:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif p == 1:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _patch(crop: np.ndarray) -> np.ndarray:
    from open_guji_cv.clustering.normalize import normalize_patch
    return normalize_patch(crop)


def recog_align(vol, stream, secs, emb: Embedder, tau=TAU, skip_d=SKIP_D, skip_e=SKIP_E):
    """在 align_volume 定下的「CADAL 段 ↔ kx 部」对应内，用字形相似度做逐字对齐。
    返回 (assignments=[(item, entry, sim)], unmatched_items, report)。"""
    cad = [[]]
    head_pages = []                                  # 每个段起始标题列所在的 djvu 页
    for it in stream:
        if it["kind"] == "h":
            cad.append([])
            head_pages.append(it["page"])
        else:
            cad[-1].append(it)
    head_secs = cad[1:]
    if not head_secs:
        return [], [it for it in stream if it["kind"] == "g"], [dict(level="volume", note="no heading found")]
    sizes = [sum(1 for it in sec if it["kind"] == "g") for sec in head_secs]
    pg = sorted({it["page"] for it in stream})
    lo, hi = candidate_radicals(secs, vol, pg)
    secs = secs[lo:hi]                               # 按印刷页码把候选部首限制在本册范围
    ssizes = [len(s["entries"]) for s in secs]
    # 页码一致性项：段起始页（印刷页 → 估计 kx 页）vs 部起始的真实 kx 页
    off = OFFSET.get(vol, 0)
    c_kx = [printed_to_kx(p + off) for p in head_pages]
    s_kx = [s["entries"][0][0] for s in secs]
    cost, pairs_all = _align_sizes(sizes, ssizes, free_last=True, free_first=True,
                                   c_kx=c_kx, s_kx=s_kx, page_w=PAGE_COST_W)
    a = pairs_all[0][2] if pairs_all else 0          # 本册第一个匹配上的 kx 部
    pairs = [(c0, c1, j0 - a, j1 - a) for (c0, c1, j0, j1) in pairs_all]
    report = [dict(level="volume", first_radical=secs[a]["radical"], cost=round(cost, 3), embedder=emb.kind)]
    # 卷首标题前的残段 ↔ 首部之前那个部（kx 侧开头免费跳过）
    jobs = []
    if cad[0] and a > 0:
        jobs.append((cad[0], [secs[a - 1]], True, False))
    for k, (ci0, ci1, sj0, sj1) in enumerate(pairs):
        items = [it for kk in range(ci0, ci1) for it in head_secs[kk]]
        jobs.append((items, secs[a + sj0:a + sj1], False, k == len(pairs) - 1))
    # 所有字头切图一次性算向量
    glyphs = [it for items, _, _, _ in jobs for it in items if it["kind"] == "g"]
    if glyphs:
        E = emb.embed(np.stack([_patch(it["crop"]) for it in glyphs]))
        for it, v in zip(glyphs, E):
            it["vec"] = v
    assignments, unmatched = [], []
    for items, ksecs, free_start, free_end in jobs:
        D = [it for it in items if it["kind"] == "g"]
        ents = [e for s in ksecs for e in s["entries"]]
        rad = "".join(s["radical"] for s in ksecs)
        rep = dict(level="section", radical=rad, cadal_pages=(D[0]["page"], D[-1]["page"]) if D else None,
                   n_detected=len(D), n_expected=len(ents), n_matched=0, mean_sim=0.0, n_lowsim=0, n_aligned=0)
        if not D or not ents:
            unmatched += D
            report.append(rep)
            continue
        tpl = emb.templates([e[2] for e in ents])
        T = np.zeros((len(ents), E.shape[1]), np.float32)
        wild = np.zeros(len(ents), bool)
        for j, e in enumerate(ents):
            v = tpl.get(e[2])
            if v is None or v.shape[0] != T.shape[1]:
                wild[j] = True
            else:
                T[j] = v
        S = np.stack([it["vec"] for it in D]) @ T.T
        S = _standardize(S)
        S[:, wild] = tau        # 通配项：只靠邻居对上才接受
        pairs_ij = _nw_align(S, skip_d, skip_e, free_start, free_end)
        pset = set(pairs_ij)
        ok = set()
        sims = []
        for (i, j) in pairs_ij:
            s = float(S[i, j])
            sims.append(s)
            nb_prev = (i - 1, j - 1) in pset or (i == 0 and j == 0) or (i == 0 and free_start)
            nb_next = (i + 1, j + 1) in pset or (i == len(D) - 1 and j == len(ents) - 1) or (i == len(D) - 1 and free_end)
            nb = int(nb_prev) + int(nb_next)
            # 接受：相似度 ≥τ 且前后邻居都对上；或 ≥τ+0.15 且一侧邻居对上；或 ≥1.0（z≈5，极高）
            if (s >= tau and nb == 2) or (s >= tau + 0.15 and nb >= 1) or s >= 1.0:
                ok.add(i)
                assignments.append((D[i], ents[j], s))
            elif s < tau:
                rep["n_lowsim"] += 1
        unmatched += [it for i, it in enumerate(D) if i not in ok]
        rep.update(n_matched=len(ok), n_aligned=len(pairs_ij), mean_sim=round(float(np.mean(sims)), 3) if sims else 0.0)
        report.append(rep)
    return assignments, unmatched, report


def _mosaic(assignments, out: Path, k=40, seed=0):
    """随机抽 k 个已赋字的切图，右侧用字体渲染赋的字，拼成一张图供人工核对标签。"""
    from PIL import Image, ImageDraw, ImageFont
    rng = np.random.default_rng(seed)
    sel = [assignments[i] for i in rng.choice(len(assignments), min(k, len(assignments)), replace=False)]
    fonts = [ImageFont.truetype(str(f), 96) for f in sorted(Path("fonts/jigmo").glob("*.ttf"))]

    def pick_font(ch):   # Jigmo/Jigmo2/Jigmo3 各覆盖一部分码位：选画得出来（非豆腐）的那个
        for f in fonts:
            try:
                if f.getmask(ch).getbbox() != f.getmask("͸").getbbox():
                    return f
            except Exception:  # noqa: BLE001
                continue
        return fonts[0] if fonts else ImageFont.load_default()
    cell_w, cell_h, cols = 260, 140, 5
    rows = (len(sel) + cols - 1) // cols
    canvas = Image.new("L", (cols * cell_w, rows * cell_h), 255)
    draw = ImageDraw.Draw(canvas)
    for n, (it, e, s) in enumerate(sel):
        r, c = divmod(n, cols)
        x0, y0 = c * cell_w, r * cell_h
        crop = Image.fromarray(it["crop"]).resize((120, 120))
        canvas.paste(crop, (x0 + 5, y0 + 10))
        draw.text((x0 + 135, y0 + 15), e[2], font=pick_font(e[2]), fill=0)
        draw.text((x0 + 135, y0 + 115), f"{s:.2f} KX{e[0]}.{e[1]:03d}", fill=0)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)


def cmd_run(a):
    """全量：检测 → 部级对齐 → 部内识别引导的逐字对齐 → 切图。
    crops/KX<page>.<pos>_<char>.png（kx2ucs 的页.位）；未赋字的切图进 crops/unk/。"""
    secs = kx_sections()
    emb = Embedder()
    outdir = CROPS if not a.dry else ROOT / "probe" / "dry"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "unk").mkdir(exist_ok=True)
    man = open(outdir / "manifest.tsv", "a", encoding="utf-8")
    sec_f = open(outdir / "sections.tsv", "a", encoding="utf-8")
    for vol in parse_vols(a.vol):
        pages = parse_pages(a.pages, vol)
        pages = body_pages(vol, pages)
        print(f"v{vol}: scanning {len(pages)} body pages (printed {pages[0] + OFFSET[vol]}-{pages[-1] + OFFSET[vol]})...", flush=True)
        stream, per_page = scan_volume(vol, pages, log=(print if a.verbose else (lambda *x: None)), keep_crops=True, man=man)
        # 卷首集目页要等检测完（拿到每页标题列数）才认得出来，扫完再从流里剔掉
        body, cut = drop_front_matter(vol, pages, per_page)
        if cut:
            keep = set(body)
            stream = [it for it in stream if it["page"] in keep]
            per_page = {p: v for p, v in per_page.items() if p in keep}
            print(f"v{vol}: dropped {cut} front-matter page(s) (printed <= {cut + OFFSET[vol]})", flush=True)
        print(f"v{vol}: scan done ({sum(pp['n'] for pp in per_page.values())} glyphs), aligning...", flush=True)
        assignments, unmatched, report = recog_align(vol, stream, secs, emb, tau=a.tau, skip_d=a.skip_d, skip_e=a.skip_e)
        n_det = sum(pp["n"] for pp in per_page.values())
        for r in report:
            print(f"v{vol} {r}", flush=True)
            if r["level"] == "section":
                sec_f.write("\t".join(str(x) for x in (vol, r["radical"], r["cadal_pages"], r["n_detected"], r["n_expected"],
                                                        r["n_matched"], r["mean_sim"], r["n_lowsim"])) + "\n")
        sec_f.flush()
        sims = np.array([s for _, _, s in assignments])
        print(f"v{vol}: detected {n_det}, assigned {len(assignments)} ({100 * len(assignments) / max(n_det, 1):.1f}%), "
              f"sim mean {sims.mean() if len(sims) else 0:.3f}, unk {len(unmatched)}", flush=True)
        if a.mosaic and assignments:
            _mosaic(assignments, ROOT / "probe" / f"mosaic_v{vol:02d}.png", k=a.mosaic)
        if a.dry:
            continue
        for it, (kxp, pos, ch, var), s in assignments:
            ok, buf = cv2.imencode(".png", it["crop"])
            if ok:   # 文件名含扩展区汉字，cv2.imwrite 在 Windows 上会写坏路径 → 自己编码后写
                (CROPS / f"KX{kxp:04d}.{pos:03d}_{ch}.png").write_bytes(buf.tobytes())
        for n, it in enumerate(unmatched):
            ok, buf = cv2.imencode(".png", it["crop"])
            if ok:
                (CROPS / "unk" / f"v{vol:02d}_p{it['page']:04d}_{n:04d}_unk.png").write_bytes(buf.tobytes())
        print(f"v{vol}: crops written", flush=True)


def cmd_calib(a):
    """校准一册：(1) 把若干页左右页边栏切出来拼成一张图（probe/margins_v<vol>.png），人工读印刷页码 → OFFSET；
    (2) 检测这些页的标题列并与 kx2ucs 部首段做对齐试算（同 run --dry），打印各段检测数 vs kx2ucs 数。"""
    vol = int(a.vol)
    pages = parse_pages(a.pages, vol)
    tiles = []
    for p in pages[:: max(1, len(pages) // 8)]:
        g = render(vol, p)
        tiles.append(cv2.copyMakeBorder(np.hstack([g[2300:3700, 40:300], g[2300:3700, 2480:2720]]), 0, 0, 0, 12, cv2.BORDER_CONSTANT, value=128))
        cv2.putText(tiles[-1], f"p{p}", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    out = ROOT / "probe" / f"margins_v{vol:02d}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.hstack(tiles))
    print(f"页边栏拼图（读页码定 OFFSET）：{out}")
    secs = kx_sections()
    stream, per_page = scan_volume(vol, pages, log=print)
    _, report = align_volume(vol, stream, secs)
    for r in report:
        print(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect"); d.add_argument("--vol", required=True); d.add_argument("--pages", required=True); d.add_argument("--debug", action="store_true")
    c = sub.add_parser("calib"); c.add_argument("--vol", required=True); c.add_argument("--pages", required=True)
    r = sub.add_parser("run"); r.add_argument("--vol", required=True); r.add_argument("--pages", default="all")
    r.add_argument("--dry", action="store_true", help="只对齐不切图（报表进 probe/dry/）"); r.add_argument("--verbose", action="store_true")
    r.add_argument("--tau", type=float, default=TAU); r.add_argument("--skip-d", type=float, default=SKIP_D); r.add_argument("--skip-e", type=float, default=SKIP_E)
    r.add_argument("--mosaic", type=int, default=0, help="抽 N 个已赋字切图拼图到 probe/mosaic_v<vol>.png 供核对")
    a = ap.parse_args()
    {"detect": cmd_detect, "calib": cmd_calib, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    main()
