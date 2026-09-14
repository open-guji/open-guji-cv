# -*- coding: utf-8 -*-
"""金标字对可疑侧的人裁页：这个半字到底是哪个字？

    python experiments/touch_resolve/build_label_review.py [--out out/label_review.html] [--controls 10]

出题纪律（review-artifact skill）：
- 卡上**不印**哪个候选是金标、哪个是识别器认的；候选顺序按卡 id 打散；
- 混入 --controls 张「金标与识别 top-1 一致」的对照卡（stratum=control），量人的基线偏差；
- 每张卡 id = `<金标id>:<above|below>`，候选顺序随卡存进 out/label_review_cards.jsonl 与页内 D.rows，
  收回时按它解码，重建页面时照旧读，id 不漂。
裁决值：opt0/opt1/opt2 = 第 N 个候选字；none = 都不是；idk = 看不清。
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

from common import INK_TH, Loader, OUT_ROOT, half_patch, jdump, seam_chosen, seam_gold, side_masks, window

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".claude/skills/review-artifact/scripts"))
from review_shell import render  # noqa: E402

TITLE = "粘连点金标字对复核"
KEY = "touch-label-review-2026-09-13-v1"


def png_uri(img: np.ndarray) -> str:
    q = (img // 16) * 16                                  # 16 级灰
    ok, buf = cv2.imencode(".png", q, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def card_image(win: np.ndarray, mask: np.ndarray, hp: np.ndarray) -> np.ndarray:
    """左：双格窗口，问的那一半正常、另一半淡化；右：那一半放大。统一高 150。"""
    H = 150
    faded = win.copy().astype(np.float32)
    faded[~mask] = 255 - (255 - faded[~mask]) * 0.12
    left = faded.astype(np.uint8)
    s = H / left.shape[0]
    left = cv2.resize(left, (max(1, int(left.shape[1] * s)), H), interpolation=cv2.INTER_AREA)
    s2 = min(H / hp.shape[0], 120 / hp.shape[1])
    right = cv2.resize(hp, (max(1, int(hp.shape[1] * s2)), max(1, int(hp.shape[0] * s2))), interpolation=cv2.INTER_AREA)
    canvas = np.full((H, left.shape[1] + 8 + 120), 255, np.uint8)
    canvas[:, : left.shape[1]] = left
    y = (H - right.shape[0]) // 2
    canvas[y: y + right.shape[0], left.shape[1] + 8: left.shape[1] + 8 + right.shape[1]] = right
    cv2.line(canvas, (left.shape[1] + 3, 0), (left.shape[1] + 3, H - 1), 200, 1)
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_ROOT / "label_review.html"))
    ap.add_argument("--controls", type=int, default=10)
    ap.add_argument("--verdicts", default=None, help="上一版读回的 HTML，带着已有裁决重发")
    a = ap.parse_args()
    per = json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))
    L = Loader()
    by_id = {it.id: it for it in L.gold_items(need_chars=True)}

    suspects, ok_pool = [], []
    for r in per:
        rk = r["rank"]["gold"]
        for side in ("above", "below"):
            v = rk[f"fused_{side}"]
            (suspects if (v is None or v > 5) else ok_pool).append((r, side))
    rng = random.Random(20260913)
    controls = rng.sample([x for x in ok_pool if x[0]["rank"]["gold"][f"fused_{x[1]}"] == 1], a.controls)
    items = [(r, s, "suspect") for r, s in suspects] + [(r, s, "control") for r, s in controls]
    rng.shuffle(items)

    rows, imgs = [], {}
    for r, side, stratum in items:
        c, _ = L.resolve(by_id[r["id"]])
        if c is None:
            continue
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        # 用**当前管线**的缝分上下：金标缝有 33/59 条坐标系过期（用户 2026-09-14 反馈「有的字切分不对」）
        above, below = side_masks(win.shape, seam_chosen(c), y0)
        mask = above if side == "above" else below
        hp = half_patch(win, mask)
        if hp is None:
            continue
        gold = c.char_above if side == "above" else c.char_below
        tk = (r["topk"]["gold"].get(side) or {}).get("fused") or []
        cands = []
        for ch in [gold] + tk[:3]:
            if ch and ch not in cands:
                cands.append(ch)
            if len(cands) >= 3:
                break
        crng = random.Random(hash((r["id"], side)) & 0xFFFF)
        crng.shuffle(cands)
        cid = f"{r['id']}:{side}"
        imgs[cid] = png_uri(card_image(win, mask, hp))
        rows.append({"id": cid, "case": r["id"], "side": side, "opts": cands, "img": cid,
                     "stratum": stratum, "stratum_weight": 1.0,
                     "pos": "上字" if side == "above" else "下字"})
    print(f"卡片 {len(rows)} 张（可疑 {sum(1 for x in rows if x['stratum']=='suspect')} + 对照 {sum(1 for x in rows if x['stratum']=='control')}）")
    jdump(rows, OUT_ROOT / "label_review_cards.jsonl".replace(".jsonl", ".json"))

    css = """
.card{background:var(--surface); border:1px solid var(--rule); border-left:3px solid transparent;
  border-radius:3px; padding:12px 13px; box-shadow:var(--shadow);}
.card[data-v^="opt"]{border-left-color:var(--ok)} .card[data-v="none"]{border-left-color:var(--zhu)}
.card[data-v="idk"]{border-left-color:var(--faint)}
.card h3{margin:0; font-family:var(--serif); font-size:14px; color:var(--muted); font-weight:500;}
.card img{width:100%; max-width:360px; image-rendering:auto; background:var(--tile); border-radius:2px; display:block; margin:8px 0 0;}
.verdicts{display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:52px; border:1px solid var(--rule-hard); border-radius:3px; background:var(--surface);
  color:var(--ink); font-family:var(--serif); font-size:26px; cursor:pointer; padding:0;}
.verdicts button.small{font-family:var(--sans); font-size:13px;}
.verdicts button:active{background:var(--sunk)} .verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
.verdicts button.opt[aria-pressed="true"]{background:var(--ok)} .verdicts button.none[aria-pressed="true"]{background:var(--zhu)}
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
    <p>每张卡只问一件事：<b>这个位置刻的是哪个字</b>。不评价切分、不管污渍。左图是上下两字的窗口，问的那个字正常显示、邻字淡成浅灰；右图是它按当前切线单独放大——切线可能不准，以左图整体读字为准。
       下面的候选字里点<b>你读出来的那个</b>；候选里没有你读出的字才点「都不是」（我事后再问）；
       只有字本身磨损、粘连或被切坏到读不出才点「看不清」。点错再点一次取消。裁决自动存回本页，右上角牌子显示存没存上。</p>
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
  const opt = (ch, i) => `<button class="opt" data-v="opt${i}" aria-pressed="${v==='opt'+i}">${esc(ch)}</button>`;
  const pad = 3 - r.opts.length;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${esc(r.pos)} · ${esc(r.case)}</h3>
    <img data-src="${r.img}" alt="">
    <div class="verdicts">${r.opts.map(opt).join('')}${'<span></span>'.repeat(pad)}
      <button class="small none" data-v="none" aria-pressed="${v==='none'}">都不是</button>
      <button class="small idk" data-v="idk" aria-pressed="${v==='idk'}">看不清</button></div>
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
  return D.rows.filter(r => verdictOf(r.id)).map(r => {
    const v = verdictOf(r.id); const ch = v.startsWith('opt') ? r.opts[+v.slice(3)] : v;
    return JSON.stringify({id: r.id, verdict: v, char: ch});
  }).join('\\n');
}
""".replace("__TITLE__", TITLE)
    verdicts = {}
    if a.verdicts:
        import re
        m = re.search(r'<script[^>]*id="data"[^>]*>(.*?)</script>', Path(a.verdicts).read_text(encoding="utf-8"), re.S)
        verdicts = json.loads(m.group(1).replace("<" + chr(92) + "/", "</")).get("verdicts", {}) if m else {}
        print(f"带上已有裁决 {len(verdicts)} 条")
    html = render(TITLE, KEY, verdicts=verdicts, css=css, page_js=page_js, payload={"rows": rows, "imgs": imgs})
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
