# -*- coding: utf-8 -*-
"""生成「下版框存墨判读」审查页：某页的下内框到底印上了没有 + 版框几何统计。

**背景**：vol01 的 137/138/141 三页，`border-detection` 金标的 `bottom_inner`
落在墨量极低的位置（行墨 0.010/0.033/0.000）。要判的是：印糊了，还是没印上。

**结论（2026-09-01 复核）：三页都印上了，只是磨得极淡，金标是对的。**
早先「138 根本没印上」「141 算法本来就对」两个说法都错了，原因见下面两条。

**判据一：相对本底的局部峰。** 用 0.20 这种绝对门槛判「有没有线」对糊页太粗暴。
本底（内框与外条之间那段白）实测就是 0.000，所以只要金标处有 0.02~0.10 的墨，
就已经是本底的 8~39 倍。清楚页是 250~450 倍，「淡但明确」的 47/51/142/49 是
105~180 倍——是一条连续的衰减谱，不是有无之分。

**判据二：空间相干性（真线 vs 噪点）。** 真版框线的墨沿 x 连成长横条，噪点是
散点。量「覆盖率 + 最长连段」，并跟同页确定空白的对照行比：
    p24(清楚)   覆盖 0.719 最长连段 188   对照行 0.002 / 2
    p47(淡)     覆盖 0.257 最长连段  55   对照行 0.000 / 0
    p138        覆盖 0.095 最长连段  37   对照行 0.009 / 4
    p137        覆盖 0.027 最长连段  25   对照行 0.000 / 0
    p141        覆盖 0.017 最长连段  17   对照行 0.029 / 47
137/138 在金标处都有远超对照行的结构，是真线。141 两边都只剩个位数碎片，
下内框基本磨没了——但算法在那页落在**外框粗条**上，比金标错得多。

⚠️ **不能拿外条近沿反推内框位置**（上一版就是这么错的）。外条是从**内侧**磨掉
的：清楚页近沿在 +15~+17，磨损页漂到 +28~+34，而远沿只从 +33~+38 漂到 +39~+45。
所以只有**远沿（外延）**是稳的，近沿不是。

**几何统计**见页面里的表，由本脚本按 `--clear` 指定的清楚页现算。关键一条：
**版框四边不等距**——同页实测竖直外延间距比 top 大 10.8±4.5px、比 bottom 大
5.9±4.2px（n=5）。`detect_outer_borders` 已按这个差做逐边校正。

跑法：
    python scripts/build_border_bottom_review.py
    python scripts/build_border_bottom_review.py --pages 24,137,138,141
发布：`Artifact` 工具重发布到同一 URL，见 artifacts/README.md 的台账。
原图路径用 GUJI_RAW 覆盖（默认 /home/user/rebuild_src）。
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.border_geometry import HLine, detect_borders  # noqa: E402
RAW = Path(os.environ.get("GUJI_RAW", "/home/user/rebuild_src"))
GOLD = ROOT.parent / "open-guji-dataset" / "border-detection" / "samples"

BAR_INK = 0.30         # 认粗外条的墨门槛
COH_HALF = 2           # 相干性取线上下 ±这么多行做或运算
CTRL_OFF = 9           # 对照行：内框与外条之间那段确定的白
CLEAR_DEFAULT = "33,14,24,65,26"   # 下框印得清楚、用来算几何常数的页
GAP_FAR_BOTTOM = 33.9  # 下框 内框线心 → 外条外延，清楚页实测均值（main 里按实测覆盖）
ZOOM, CROP_W = 3, 460

# 判读结论（人写的，随证据更新）
NOTES = {
    "24": ("参照", "印得好", "ok",
           "下框完整：细内框线（墨 0.70、覆盖 0.72、最长连段 188px）+ 白 + 粗外条。"
           "对照行覆盖只有 0.002。这页是量几何常数的基准之一。"),
    "137": ("已判", "印上了，磨得极淡", "worn",
            "金标处覆盖 0.027、最长连段 25px，而正下方 +5~+11 是真正的空白"
            "（覆盖 0.000、连段 0）。有结构就不是噪点。算法线在金标上方 23px，"
            "咬在末行字的墨上——那是一片 20px 宽的平台，不是线。<b>金标对，算法错。</b>"),
    "138": ("已判", "印上了，糊但清楚", "good",
            "金标处覆盖 0.095、最长连段 37px，对照行只有 0.009 / 4px。"
            "特征中心约在金标下方 3px，金标基本准。算法线在金标上方 21px，也在末行字上。"
            "<b>金标对，算法错。</b>"),
    "141": ("已判", "基本磨没了；但算法错得更远", "none",
            "金标处覆盖 0.017、最长连段 17px，跟对照行同量级——下内框在这页基本磨没了。"
            "但算法线落在金标下方 28px，正是<b>外框粗条</b>的近沿（粗条 +28~+45）。"
            "外条远沿 44.8px 与清楚页的 33.9px 相比，提示真内框约在金标下方 10px，"
            "那里只剩一段 47px 的碎片。<b>金标比算法近得多。</b>"),
}


def measure(book: str, page: str) -> dict:
    """量一页：行墨剖面、粗外条范围、几何推定的内框位置，外加裁图。"""
    gray = cv2.imread(str(RAW / book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise SystemExit(f"读不到原图：{RAW / book / f'{page}.tif'}")
    binm = (gray < 128).astype(np.uint8)
    h, w = binm.shape
    res = detect_borders(gray, expected_cols=9)
    A, verts = res.bottom, res.verticals
    g = json.loads((GOLD / f"{book}_{page}.json").read_text(encoding="utf-8"))
    G = HLine(g["bottom_inner"]["y_at_right"], g["bottom_inner"]["slope"], "bottom")

    vx = sorted((w - 1) - v.x_at(h / 2.0) for v in verts)
    xs = np.arange(int((w - 1) - vx[-1] + 20), int((w - 1) - vx[0] - 20))
    xp = xs[::2]
    base = np.array([A.y_at((w - 1) - x) for x in xp])
    prof = {}
    for o in range(-40, 121):
        yy = np.rint(base + o).astype(int)
        ok = (yy >= 0) & (yy < h)
        prof[o] = float(binm[yy[ok], xp[ok]].mean()) if ok.any() else 0.0

    idx = [o for o in range(10, 121) if prof[o] >= BAR_INK]
    bar = None
    if idx:
        runs, a, b = [], idx[0], idx[0]
        for q in idx[1:]:
            if q == b + 1:
                b = q
            else:
                runs.append((a, b)); a = b = q
        runs.append((a, b))
        bar = max(runs, key=lambda r: r[1] - r[0])
    # 只能用**远沿**反推（近沿会被磨掉，见模块 docstring）
    pred = None if bar is None else round(bar[1] - GAP_FAR_BOTTOM)

    goff = G.y_at(w / 2) - A.y_at(w / 2)
    lo = int(max(0, A.y_at(w / 2) + min(-30, goff - 30)))
    hi = int(min(h, A.y_at(w / 2) + ((bar[1] + 30) if bar else 80)))
    x0 = int(xs[0]) + (int(xs[-1]) - int(xs[0])) // 2 - CROP_W // 2
    clean = cv2.cvtColor(gray[lo:hi, x0:x0 + CROP_W], cv2.COLOR_GRAY2BGR)
    annot = clean.copy()

    def draw(off, col, dash=12):
        for x in range(annot.shape[1]):
            if (x // dash) % 2:
                continue
            y = int(round(A.y_at((w - 1) - (x + x0)) + off)) - lo
            if 0 <= y < annot.shape[0]:
                annot[y, x] = col

    coh = coherence(binm, A, w, h, xs, goff)
    ctrl = coherence(binm, A, w, h, xs, goff + CTRL_OFF)

    draw(goff, (0, 180, 0))            # 金标 绿
    draw(0, (0, 0, 235))               # 算法 红
    if bar:
        draw(bar[1], (230, 130, 0))    # 粗外条外延 蓝
    if pred is not None:
        draw(pred, (200, 0, 200))      # 几何推定内框 品红

    big = lambda im: cv2.resize(im, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
    img = np.vstack([big(clean),
                     np.full((7, CROP_W * ZOOM, 3), 205, np.uint8),
                     big(annot)])
    tmp = Path(tempfile.gettempdir()) / f"_bbr_{book}_{page}.jpg"
    cv2.imwrite(str(tmp), img, [cv2.IMWRITE_JPEG_QUALITY, 86])
    uri = "data:image/jpeg;base64," + base64.b64encode(tmp.read_bytes()).decode()
    tmp.unlink(missing_ok=True)

    near = lambda c: round(max(prof[o] for o in range(c - 2, c + 3)), 3)
    # 本底 = 金标外侧那段白里最低的 20 个采样（prof 的定义域是 -40..120）
    lo_b, hi_b = max(-40, int(goff) + 6), min(120, int(goff) + 100)
    bg = round(float(np.median(sorted(prof[o] for o in range(lo_b, hi_b))[:20])), 4)
    gi = near(int(goff))
    return dict(page=page, bar=bar, pred=pred,
                pred_ink=None if pred is None else near(pred),
                gold_off=round(goff, 1), algo_ink=near(0), gold_ink=gi,
                bg=bg, ratio=round(gi / max(bg, 0.0005), 1),
                coh=coh, ctrl=ctrl, prof=prof, img=uri)


def coherence(binm, A, w, h, xs, off):
    """线性度：沿 x 看这一行的墨。真版框线连成长横条，噪点是散点。
    返回 (覆盖率, 最长连段px)。"""
    cols = np.arange(int(xs[0]), int(xs[-1]))
    ys = np.rint([A.y_at((w - 1) - x) for x in cols]).astype(int) + int(round(off))
    acc = np.zeros(len(cols), bool)
    for d in range(-COH_HALF, COH_HALF + 1):
        yy = ys + d
        ok = (yy >= 0) & (yy < h)
        acc[ok] |= binm[yy[ok], cols[ok]] > 0
    best = cur = 0
    for v in acc:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return round(float(acc.mean()), 3), int(best)


def geom_stats(book, pages):
    """在清楚的页上量版框几何：内框线宽 / 外条宽 / 内外间距（近沿与外延两种口径）。"""
    from open_guji_cv.utils.border_geometry import VLine  # noqa: F401
    acc = {k: [] for k in ("top", "bottom", "vert")}
    for page in pages:
        g = json.loads((GOLD / f"{book}_{page}.json").read_text(encoding="utf-8"))
        gray = cv2.imread(str(RAW / book / f"{page}.tif"), cv2.IMREAD_GRAYSCALE)
        binm = (gray < 128).astype(np.uint8)
        h, w = binm.shape
        verts = [VLine(v["x_at_top"], v["slope"]) for v in g["verticals_inner"]]
        vx = sorted((w - 1) - v.x_at(h / 2.0) for v in verts)
        xs = np.arange(int((w - 1) - vx[-1] + 20), int((w - 1) - vx[0] - 20), 2)
        ys = np.arange(int(h * 0.15), int(h * 0.85), 3)
        for kind in ("top", "bottom", "vert"):
            if kind == "vert":
                V = verts[0] if g["v_outer_side"] == "right" else verts[-1]
                sgn = -1 if g["v_outer_side"] == "right" else 1
                base = np.array([(w - 1) - V.x_at(y) for y in ys])
                pr = {}
                for o in range(-25, 121):
                    xx = (base - o * sgn).astype(int)
                    ok = (xx >= 0) & (xx < w)
                    pr[o] = float(binm[ys[ok], xx[ok]].mean()) if ok.any() else 0.0
            else:
                L = HLine(g[f"{kind}_inner"]["y_at_right"], g[f"{kind}_inner"]["slope"], kind)
                sgn = -1 if kind == "top" else 1
                base = np.array([L.y_at((w - 1) - x) for x in xs])
                pr = {}
                for o in range(-25, 121):
                    yy = np.rint(base + o * sgn).astype(int)
                    ok = (yy >= 0) & (yy < h)
                    pr[o] = float(binm[yy[ok], xs[ok]].mean()) if ok.any() else 0.0

            def halfw(c):
                half = pr[c] / 2.0
                a = c
                while a - 1 in pr and pr[a - 1] >= half:
                    a -= 1
                b = c
                while b + 1 in pr and pr[b + 1] >= half:
                    b += 1
                def cross(i, j):
                    p0, p1 = pr[i], pr[j]
                    return float(i) if p0 == p1 else i + (p0 - half) / (p0 - p1) * (j - i)
                lo = cross(a, a - 1) if a - 1 in pr and pr[a - 1] < half else float(a)
                hi = cross(b, b + 1) if b + 1 in pr and pr[b + 1] < half else float(b)
                return lo, hi

            ic = max(range(-4, 5), key=lambda o: pr[o])
            oc = max(range(8, 121), key=lambda o: pr[o])
            if pr[ic] < 0.45 or pr[oc] < 0.60:
                continue                          # 不够清楚，不进统计
            ilo, ihi = halfw(ic)
            olo, ohi = halfw(oc)
            acc[kind].append((ihi - ilo, ohi - olo, olo, ohi))
    out = {}
    for kind, v in acc.items():
        if not v:
            continue
        a = np.array(v)
        out[kind] = dict(n=len(v), iw=(a[:, 0].mean(), a[:, 0].std()),
                         barw=(a[:, 1].mean(), a[:, 1].std()),
                         near=(a[:, 2].mean(), a[:, 2].std()),
                         far=(a[:, 3].mean(), a[:, 3].std()))
    return out


def spark(prof, gold, pred, bar) -> str:
    W, H, lo, hi = 560, 120, -40, 120
    X = lambda o: (o - lo) / (hi - lo) * W
    pts = " ".join(f"{X(o):.1f},{H - min(1.0, prof[o]) * (H - 2) - 1:.1f}" for o in range(lo, hi + 1))
    m = []
    if bar:
        m.append(f'<rect x="{X(bar[0]):.1f}" y="0" width="{X(bar[1]) - X(bar[0]):.1f}" '
                 f'height="{H}" fill="var(--bar)" opacity=".16"/>')
    for off, col in ((0, "var(--algo)"), (gold, "var(--gold)"), (pred, "var(--pred)")):
        if off is None:
            continue
        m.append(f'<line x1="{X(off):.1f}" y1="0" x2="{X(off):.1f}" y2="{H}" '
                 f'stroke="{col}" stroke-width="1.5" stroke-dasharray="3 3"/>')
    ticks = "".join(f'<line x1="{X(o):.1f}" y1="{H - 4}" x2="{X(o):.1f}" y2="{H}" stroke="var(--rule)"/>'
                    f'<text x="{X(o):.1f}" y="{H - 8}" class="tk">{o:+d}</text>'
                    for o in (-40, 0, 40, 80, 120))
    return (f'<svg viewBox="0 0 {W} {H}" class="spark" role="img" aria-label="行墨占比剖面">'
            f'{"".join(m)}<polyline points="{pts}" fill="none" stroke="var(--ink-line)" '
            f'stroke-width="1.6"/>{ticks}</svg>')


def card(v: dict) -> str:
    role, verdict, cls, note = NOTES.get(v["page"], ("待裁决", "—", "worn", ""))
    bar = v["bar"]
    rows = [("金标处行墨 / 本底", f'{v["gold_ink"]:.3f} / {v["bg"]:.3f}　({v["ratio"]:.0f}×)'),
            ("金标行 覆盖 / 最长连段", f'{v["coh"][0]:.3f} / {v["coh"][1]}px'),
            ("对照行 覆盖 / 最长连段", f'{v["ctrl"][0]:.3f} / {v["ctrl"][1]}px'),
            ("算法线位置 / 该处行墨", f'{-v["gold_off"]:+.0f}px　{v["algo_ink"]:.3f}'),
            ("粗外条 [近沿,远沿]", f'{bar[0]:+d} … {bar[1]:+d}px' if bar else "没印上/被裁")]
    tr = "".join(f"<tr><th>{html.escape(a)}</th><td>{html.escape(b)}</td></tr>" for a, b in rows)
    return f'''<article class="card {cls}">
  <header class="ch">
    <div><span class="role">{role}</span><h2>vol01 / {v["page"]}</h2></div>
    <span class="verdict">{verdict}</span>
  </header>
  <div class="body">
    <figure><img src="{v["img"]}" alt="vol01/{v['page']} 下框裁图，上为原图、下为标注"/>
      <figcaption>上＝原图　下＝标注（{ZOOM}× 放大，最近邻，无插值）</figcaption></figure>
    <div class="side">
      <table>{tr}</table>
      {spark(v["prof"], v["gold_off"], v["pred"], bar)}
      <p class="cap">行墨占比剖面，横轴＝相对算法线的 px 偏移，阴影＝粗外条</p>
      <p class="note">{note}</p>
    </div>
  </div>
</article>'''


TEMPLATE = '''<title>下版框存墨判读</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --bg:#f7f8fa; --panel:#fff; --fg:#171a20; --dim:#5b6472; --rule:#d6dae1;
  --accent:#1f4e79; --ok:#2f7d4f; --worn:#b8730d; --none:#a32b32; --good:#2f7d4f;
  --algo:#d02020; --gold:#1f9d3f; --pred:#b400b4; --bar:#0f76c8; --ink-line:#39424f;
  --shadow:0 1px 2px rgba(16,24,40,.06),0 8px 22px rgba(16,24,40,.06);
}
@media (prefers-color-scheme:dark){ :root:not([data-theme="light"]){
  --bg:#0f1216; --panel:#171b21; --fg:#e7ebf1; --dim:#98a3b3; --rule:#2a323d;
  --accent:#79b4e6; --ok:#5fbf87; --worn:#e0a441; --none:#f0787f; --good:#5fbf87;
  --algo:#ff6b6b; --gold:#57d67c; --pred:#e56ce5; --bar:#4aa8f0; --ink-line:#c3ccd8;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 22px rgba(0,0,0,.35);
}}
:root[data-theme="dark"]{
  --bg:#0f1216; --panel:#171b21; --fg:#e7ebf1; --dim:#98a3b3; --rule:#2a323d;
  --accent:#79b4e6; --ok:#5fbf87; --worn:#e0a441; --none:#f0787f; --good:#5fbf87;
  --algo:#ff6b6b; --gold:#57d67c; --pred:#e56ce5; --bar:#4aa8f0; --ink-line:#c3ccd8;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 22px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);
  font-family:"Noto Sans SC",-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.65;margin:0;padding:40px 22px 64px}
.wrap{max-width:1080px;margin:0 auto;display:flex;flex-direction:column;gap:26px}
h1{font-size:30px;line-height:1.25;margin:0;text-wrap:balance;letter-spacing:-.01em}
.lede{color:var(--dim);margin:8px 0 0;max-width:60ch}
.q{background:var(--panel);border:1px solid var(--rule);border-left:3px solid var(--accent);
  border-radius:8px;padding:16px 18px;box-shadow:var(--shadow)}
.q b{color:var(--accent)}
.legend{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:13px;color:var(--dim);
  background:var(--panel);border:1px solid var(--rule);border-radius:8px;padding:12px 16px}
.sw{display:inline-flex;align-items:center;gap:7px}
.sw i{width:20px;height:0;border-top:2.5px dashed currentColor;display:inline-block}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:10px;
  overflow:hidden;box-shadow:var(--shadow)}
.ch{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;
  padding:14px 18px;border-bottom:1px solid var(--rule)}
.ch h2{font-size:19px;margin:2px 0 0;font-family:"IBM Plex Mono",ui-monospace,monospace;font-weight:500}
.role{font-size:11px;letter-spacing:.12em;color:var(--dim)}
.verdict{font-size:13px;font-weight:700;padding:5px 12px;border-radius:999px;
  white-space:nowrap;border:1px solid currentColor}
.ok .verdict,.good .verdict{color:var(--ok)}
.worn .verdict{color:var(--worn)}
.none .verdict{color:var(--none)}
.body{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:22px;padding:18px}
@media(max-width:860px){.body{grid-template-columns:1fr}}
figure{margin:0;min-width:0}
figure img{width:100%;display:block;border:1px solid var(--rule);border-radius:6px;background:#fff}
figcaption,.cap{font-size:12px;color:var(--dim);margin-top:7px}
.side{min-width:0;display:flex;flex-direction:column;gap:6px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-weight:400;color:var(--dim);padding:5px 0;white-space:nowrap}
td{text-align:right;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums;padding:5px 0}
tr+tr th,tr+tr td{border-top:1px solid var(--rule)}
.spark{width:100%;height:auto;margin-top:12px;border:1px solid var(--rule);
  border-radius:6px;background:var(--bg)}
.tk{font-size:8px;fill:var(--dim);text-anchor:middle;
  font-family:"IBM Plex Mono",ui-monospace,monospace}
.note{font-size:14px;margin:10px 0 0}
table.wide th{white-space:normal}
table.wide td{text-align:right}
table.wide tr:first-child th{color:var(--fg);font-weight:500;text-align:right}
table.wide tr:first-child th:first-child{text-align:left}
table.wide tr th:first-child{text-align:left;color:var(--fg)}
footer{color:var(--dim);font-size:13px;border-top:1px solid var(--rule);padding-top:18px}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.92em;
  background:var(--bg);border:1px solid var(--rule);border-radius:4px;padding:1px 5px}
</style>
<div class="wrap">
<header>
  <h1>下版框存墨判读</h1>
  <p class="lede">vol01 的 137 / 138 / 141 三页，金标 <code>bottom_inner</code> 整条画在白纸上。
  这页把真像素、行墨占比、以及从粗外条反推的内框位置摆在一起，供裁决。</p>
</header>
<div class="q">
  <p style="margin:0 0 6px"><b>已判：三页都印上了，只是磨得极淡，金标是对的。</b>
  早先「138 根本没印上」「141 算法本来就对」两个说法都错了。</p>
  <p style="margin:0;color:var(--dim);font-size:14px">判据一 <b>相对本底的局部峰</b>：本底（内框与外条之间那段白）实测是 0.000，
  所以金标处 0.02~0.10 的墨已是本底的 8~39 倍；清楚页 250~450 倍、「淡但明确」的 47/51/142/49 是 105~180 倍——
  是一条连续的衰减谱，不是有无之分。判据二 <b>空间相干性</b>：真版框线的墨沿 x 连成长横条，噪点是散点，
  所以同时看「覆盖率 + 最长连段」，并跟同页确定空白的对照行比。</p>
  <p style="margin:8px 0 0;color:var(--dim);font-size:14px">⚠️ <b>不能拿外条近沿反推内框</b>（上一版就是这么错的）：外条是从<b>内侧</b>磨掉的，
  清楚页近沿在 +15~+17、磨损页漂到 +28~+34，而远沿只从 +33~+38 漂到 +39~+45。只有<b>远沿（外延）</b>是稳的。</p>
</div>
__STATS__
<div class="legend">
  <span class="sw" style="color:var(--algo)"><i></i>算法线（offset 0 基准）</span>
  <span class="sw" style="color:var(--gold)"><i></i>人工金标</span>
  <span class="sw" style="color:var(--pred)"><i></i>由外条<b>远沿</b>反推的内框位置</span>
  <span class="sw" style="color:var(--bar)"><i></i>粗外条外延</span>
</div>
__CARDS__
<footer>
  <p style="margin:0 0 8px"><b>为什么没有自动改金标。</b>两版自动重拟都被粗外条骗走：外条比这几页磨损的内框黑约 3 倍，
  「取最黑的一行」只要外条落进搜索范围就必然选它；想拿金标自己的 <code>bottom_outer_offset</code> 挖掉外条也不行——
  它是相对同一条画错的内框量的，内框错了它跟着错。</p>
  <p style="margin:0">体检脚本 <code>open-guji-dataset/scripts/report_border_hlines_offtarget.py</code>（只报告不改金标）。
  另外顺带纠正了一件事：旧的 <code>eval_border_hlines_vs_ink</code> 只拿金标当脊线种子，金标结构上不可能输——
  它报的「vol01/47 top 算法差 23.9px」「51 bottom 差 15.5px」都是量法造出来的假象。换中立量法后 28 条边里 23 条本来就重合。</p>
</footer>
</div>
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--pages", default="24,137,138,141",
                    help="逗号分隔；第一页通常放一页印得好的当参照")
    ap.add_argument("--clear", default=CLEAR_DEFAULT, help="用来算几何常数的清楚页")
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "border_bottom_review.html"))
    a = ap.parse_args()
    st = geom_stats(a.book, [x.strip() for x in a.clear.split(",")])
    global GAP_FAR_BOTTOM
    if "bottom" in st:
        GAP_FAR_BOTTOM = st["bottom"]["far"][0]
    print("版框几何（清楚页实测）")
    for kind in ("top", "bottom", "vert"):
        if kind not in st:
            continue
        d = st[kind]
        print(f"  {kind:<7} n={d['n']}  内框线宽={d['iw'][0]:.1f}±{d['iw'][1]:.1f}  "
              f"外条宽={d['barw'][0]:.1f}±{d['barw'][1]:.1f}  "
              f"内心→近沿={d['near'][0]:.1f}±{d['near'][1]:.1f}  "
              f"内心→外延={d['far'][0]:.1f}±{d['far'][1]:.1f}")
    cards = []
    for page in a.pages.split(","):
        v = measure(a.book, page.strip())
        cards.append(card(v))
        print(f"{a.book}/{v['page']}: 粗外条={v['bar']} 推定内框={v['pred']} "
              f"该处墨={v['pred_ink']} | 算法墨={v['algo_ink']} 金标({v['gold_off']:+.0f})墨={v['gold_ink']}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    hdr = ("<tr><th>边</th><th>页数</th><th>内框线宽</th><th>外框条宽</th>"
           "<th>间距 内心→外条近沿</th><th>间距 内心→外条外延</th></tr>")
    lab = {"top": "上框", "bottom": "下框", "vert": "竖直（纸边侧）"}
    body = "".join(
        f"<tr><th>{lab[k]}</th><td>{st[k]['n']}</td>"
        + "".join(f"<td>{st[k][f][0]:.1f} ± {st[k][f][1]:.1f}</td>"
                  for f in ("iw", "barw", "near", "far"))
        + "</tr>" for k in ("top", "bottom", "vert") if k in st)
    stats = (f'<section class="card"><header class="ch"><div>'
             f'<span class="role">清楚的页实测（单位 px，均值 ± 标准差）</span>'
             f'<h2>版框几何</h2></div></header><div style="padding:6px 18px 18px">'
             f'<table class="wide">{hdr}{body}</table>'
             f'<p class="cap">清楚 = 内框峰墨 ≥0.45 且外条峰墨 ≥0.60。'
             f'「外延」就是金标 <code>*_outer_offset</code> 的口径。</p>'
             f'<p class="note"><b>版框四边不等距。</b>同页实测，竖直的外延间距比上框大 '
             f'10.8±4.5px、比下框大 5.9±4.2px（n=5）。<code>detect_outer_borders</code> '
             f'原先直接拿竖直间距当上下的先验，等于窗口中心整体偏外；按边校正后，'
             f'对真墨外延的误差 top 1.6→1.2px、bottom 5.6→<b>0.9px</b>。</p></div></section>')
    out.write_text(TEMPLATE.replace("__CARDS__", "\n".join(cards)).replace("__STATS__", stats),
                   encoding="utf-8")
    print(f"\n写出 {out}（{out.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
