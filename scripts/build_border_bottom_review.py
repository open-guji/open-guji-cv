# -*- coding: utf-8 -*-
"""生成「下版框存墨判读」审查页：判断某页的下内框到底印上了没有。

**背景**：vol01 的 137/138/141 三页，`border-detection` 金标的 `bottom_inner`
整条画在白纸上（线上行墨 0.010/0.033/0.000）。要裁决的是一句话——这三页的
下内框是**印糊了**（按残墨重标金标）还是**根本没印上**（标成缺失）。

**定位办法**：这本书的下框是「细内框线 + 约 17px 白 + 约 19px 粗外条」。
粗外条即使磨损也还认得出，所以用 **外条起点 − BAR_TO_INNER** 反推内框该在
哪，再看那儿有没有墨。常数取自 5 页印得好的正文页（vol01/24、26、65、33、14
实测 17/15/16/17/18px）。

⚠️ 注意间距口径：这里的 17px 是「内框线心 → 粗外条**近**沿」。金标里的
`bottom_outer_offset`（以及页级的内外间距 38.4±4.0px）量的是**外延**，也就是
外条的**远**沿——外条本身约 19px 厚，两个数不冲突，但别混用。

**为什么这个脚本只出图不改金标**：自动重拟试过两版，都被粗外条骗走——外条
比这几页磨损的内框黑约 3 倍，「取最黑的一行」只要外条落进搜索范围就必然选
它；想拿金标自己的 `bottom_outer_offset` 挖掉外条也不行，它是相对同一条画错
的内框量的，内框错了它跟着错。所以做成人裁页面。

跑法：
    python scripts/build_border_bottom_review.py                    # 默认那三页 + 参照页
    python scripts/build_border_bottom_review.py --pages 24,137,138,141
    python scripts/build_border_bottom_review.py --out /tmp/x.html
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

BAR_TO_INNER = 17      # 内框线心 → 粗外条近沿，健康页实测中位（见模块 docstring）
BAR_INK = 0.30         # 认粗外条的墨门槛
ZOOM, CROP_W = 3, 460

# 判读结论（人写的，随证据更新）
NOTES = {
    "24": ("参照", "印得好", "ok",
           "下框完整：细内框线（墨 0.70）+ 约 17px 白 + 约 19px 粗外条（墨 1.00）。"
           "金标与算法完全重合。这页是量「内框↔外条」几何常数的基准之一。"),
    "137": ("待裁决", "印上了，磨成虚线", "worn",
            "推定内框处是一排断续墨点，墨 0.102——只有健康页的七分之一，但位置分毫不差。"
            "算法咬在末行字的墨上（0.197 是一片 20px 宽的平台，不是线），金标落在两者之间的白纸上。"),
    "138": ("待裁决", "根本没印上", "none",
            "推定内框处墨 0.002，整条是白纸。往下紧贴粗外条有一点 0.05~0.07 的散墨，"
            "更像外条自己的毛边而不是另一条线。这页只有外条。"),
    "141": ("待裁决", "印上了，算法本来就对", "good",
            "推定内框 = 算法线（差 1px），墨 0.407，是三页里最结实的一条。"
            "金标偏上 28px 落在白纸上。外条磨成 0.36 的细痕，再往下扫描就裁掉了。"),
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
    pred = None if bar is None else bar[0] - BAR_TO_INNER

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
    return dict(page=page, bar=bar, pred=pred,
                pred_ink=None if pred is None else near(pred),
                gold_off=round(goff, 1), algo_ink=near(0), gold_ink=near(int(goff)),
                prof=prof, img=uri)


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
    rows = [("算法线 (offset 0)", f'{v["algo_ink"]:.3f}'),
            (f'金标 ({v["gold_off"]:+.0f}px)', f'{v["gold_ink"]:.3f}'),
            (f'推定内框 ({v["pred"]:+d}px)' if v["pred"] is not None else "推定内框",
             f'{v["pred_ink"]:.3f}' if v["pred_ink"] is not None else "—"),
            ("粗外条", f'{bar[0]:+d} … {bar[1]:+d}px' if bar else "没印上/被裁")]
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
  <p style="margin:0 0 6px"><b>要判的一句话：</b>这三页的下内框是<b>印糊了</b>（那就按残墨重标金标）还是<b>根本没印上</b>（那就该标成缺失）。</p>
  <p style="margin:0;color:var(--dim);font-size:14px">定位办法：这本书的下框是「细内框线 + 约 17px 白 + 约 19px 粗外条」。
  粗外条即使磨损也还认得出，所以用<b>外条起点减 17px</b> 反推内框该在哪，再看那儿有没有墨。
  常数取自 5 页印得好的正文页（vol01/24、26、65、33、14 实测 17/15/16/17/18px）。</p>
</div>
<div class="legend">
  <span class="sw" style="color:var(--algo)"><i></i>算法线（offset 0 基准）</span>
  <span class="sw" style="color:var(--gold)"><i></i>人工金标</span>
  <span class="sw" style="color:var(--pred)"><i></i>几何推定的内框位置</span>
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
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "border_bottom_review.html"))
    a = ap.parse_args()
    cards = []
    for page in a.pages.split(","):
        v = measure(a.book, page.strip())
        cards.append(card(v))
        print(f"{a.book}/{v['page']}: 粗外条={v['bar']} 推定内框={v['pred']} "
              f"该处墨={v['pred_ink']} | 算法墨={v['algo_ink']} 金标({v['gold_off']:+.0f})墨={v['gold_ink']}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.replace("__CARDS__", "\n".join(cards)), encoding="utf-8")
    print(f"\n写出 {out}（{out.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
