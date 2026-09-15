# -*- coding: utf-8 -*-
"""从顺序闸挡着的多候选切点里**抽样**出审查页：估计「这批放行会切坏多少字」。

    python experiments/touch_resolve/build_pending_sample.py [--book vol02] [--n 60]

背景（overview `Step3-逐字切分/11-明日待办.md` 的 A/B 决策）：vol02 全书顺序闸挡着 1073 条多候选切点，
全裁一遍要 3–4 小时。先抽 60 条让人 10 分钟判断「现役选的那条切法对不对」，据此估算整批的错误率，
再决定「全裁（A）」还是「放行 + 事后抽查（B）」。

出题纪律（review-artifact skill）：
- **不印**算法选了哪条、也不印 U-Net 的意见——只问「图上这条绿线切得对不对」；
- 分层抽样：按「所选切法与 U-Net 的分歧块」分三档（<20 / 20–60 / 60–100）各抽 1/3，
  每档的错误率分开估，再按整批的档位分布加权，比均匀抽样准；
- 每张卡存 `stratum`（档位）与 `stratum_weight`（该档在整批里的占比 ÷ 该档抽样数），收回时直接加权。
裁决值：ok = 切得对 / bad = 切坏了 / idk = 看不清。
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT_ROOT  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".claude/skills/review-artifact/scripts"))
from review_shell import render  # noqa: E402

TITLE = "切分放行抽查"
KEY = "cut-pending-sample-2026-09-15-v1"
BANDS = [("近似", 0, 20), ("中等", 20, 60), ("较大", 60, 100)]


def png_uri(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    st, ic = ProductStore(), ImageCache()
    pool: list[dict] = []
    for pg in range(1, 400):
        cells = st.read(a.book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            if not cc.ok:
                continue
            cm = {c.slot: c for c in cc.cells if c.sub is None}
            for cp in (cc.cut_candidates or []):
                if cp.chosen_by == "human" or len(cp.candidates) < 2:
                    continue
                up, dn = cm.get(cp.slot_above), cm.get(cp.slot_below)
                if up is None or dn is None:
                    continue
                d = cp.candidates[cp.chosen].dis_unet
                if d is None:
                    continue
                pool.append({"page": pg, "col": cc.col, "slot": cp.slot_above, "dis": int(d),
                             "y": float(cp.y), "chosen": cp.candidates[cp.chosen],
                             "x": [int(round(v)) for v in cc.content_x],
                             "y0": int(round(up.y0)), "y1": int(round(dn.y1))})
    print(f"顺序闸挡着的多候选切点 {len(pool)} 条")
    bands: dict[str, list] = {n: [] for n, _, _ in BANDS}
    for r in pool:
        for n, lo, hi in BANDS:
            if lo <= r["dis"] < hi:
                bands[n].append(r)
                break
    for n, _, _ in BANDS:
        print(f"  {n}: {len(bands[n])} ({len(bands[n]) / max(1, len(pool)):.1%})")
    rng = random.Random(20260915)
    per_band = max(1, a.n // len(BANDS))
    picked = []
    for n, _, _ in BANDS:
        b = bands[n]
        if not b:
            continue
        take = rng.sample(b, min(per_band, len(b)))
        w = (len(b) / max(1, len(pool))) / max(1, len(take))      # 该档占比 ÷ 抽样数
        for r in take:
            picked.append({**r, "stratum": n, "stratum_weight": round(w, 6)})
    rng.shuffle(picked)
    print(f"抽 {len(picked)} 条")

    rows, imgs = [], {}
    for r in picked:
        path = ic.get(a.book, "column_image", column_key(r["page"], r["col"]))
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
        if img is None:
            continue
        x_lo, x_hi = r["x"]
        pad = 8
        y0, y1 = max(0, r["y0"] - pad), min(img.shape[0], r["y1"] + pad)
        win = img[y0:y1, x_lo:x_hi]
        vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
        ch = r["chosen"]
        seam = (np.full(x_hi - x_lo, int(round(r["y"]))) if ch.y is None else np.asarray(ch.y, dtype=int))
        pts = [(k, int(round(v - y0))) for k, v in enumerate(seam)]
        for p1, p2 in zip(pts, pts[1:]):
            cv2.line(vis, p1, p2, (0, 170, 0), 2)
        H = 300
        s = H / vis.shape[0]
        vis = cv2.resize(vis, (max(1, int(vis.shape[1] * s)), H), interpolation=cv2.INTER_AREA)
        cid = f"{a.book}:{r['page']}:{r['col']}:{r['slot']}"
        imgs[cid] = png_uri(vis)
        rows.append({"id": cid, "img": cid, "stratum": r["stratum"], "stratum_weight": r["stratum_weight"],
                     "pos": f"p{r['page']} 列{r['col']}"})
    print(f"卡片 {len(rows)} 张：{Counter(x['stratum'] for x in rows)}")

    css = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
.card[data-v="ok"]{border-left-color:var(--ok)} .card[data-v="bad"]{border-left-color:var(--zhu)}
.card[data-v="idk"]{border-left-color:var(--faint)}
.card h3{margin:0; font-family:var(--serif); font-size:14px; color:var(--muted); font-weight:500;}
.card img{width:100%; max-width:300px; background:var(--tile); border-radius:2px; display:block; margin:8px 0 0;}
.verdicts{display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:48px; border:1px solid var(--rule-hard); border-radius:3px; background:var(--surface);
  color:var(--ink); font-size:14px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.ok[aria-pressed="true"]{background:var(--ok)}
.verdicts button.bad[aria-pressed="true"]{background:var(--zhu)}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
"""
    page_js = """
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么裁</summary>
    <p>每张图是**上下两个字**，绿线是算法要切的位置。只问一件事：<b>这条线切得对不对</b>。
       切在两字之间、没把哪个字的笔画划给邻字 → <b>切得对</b>；
       把一个字的笔画（哪怕只是一撇一点）划给了另一个字 → <b>切坏了</b>；
       字本身糊到看不出该切哪 → <b>看不清</b>。不用管线是直的还是折的。
       这批是抽样，用来估算「这类切点整体有多少切坏」，所以**凭第一眼判断即可，不必纠结**。</p>
  </details>
  <div class="ctrl">
    <div class="seg" id="filter">
      <button data-f="todo" aria-pressed="true">未裁</button>
      <button data-f="all"  aria-pressed="false">全部</button>
      <button data-f="done" aria-pressed="false">已裁</button>
    </div>
    <button class="ghost" id="copy">复制</button>
    <button class="ghost" id="reset">清空</button>
  </div>
  <div class="list" id="list"></div>
</div>
<div class="sheet" id="sheet" hidden><div class="sheet-in">
  <h2>裁决结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;
function card(r){
  const v = verdictOf(r.id);
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.pos)}</h3>
    <img data-src="${r.img}" alt="">
    <div class="verdicts">
      <button class="ok"  data-v="ok"  aria-pressed="${v==='ok'}">切得对</button>
      <button class="bad" data-v="bad" aria-pressed="${v==='bad'}">切坏了</button>
      <button class="idk" data-v="idk" aria-pressed="${v==='idk'}">看不清</button>
    </div>
  </article>`;
}
let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
document.addEventListener('click', e => {
  const b = e.target.closest('#filter button'); if (!b) return;
  filter = b.dataset.f;
  [...b.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  draw();
});
function afterVerdict(){ if (filter !== 'all') draw(); }
function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r =>
    JSON.stringify({id: r.id, verdict: verdictOf(r.id), stratum: r.stratum, w: r.stratum_weight})
  ).join('\\n');
}
""".replace("__TITLE__", TITLE)
    html = render(TITLE, KEY, verdicts={}, css=css, page_js=page_js, payload={"rows": rows, "imgs": imgs})
    out = Path(a.out) if a.out else OUT_ROOT / "pending_sample.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
