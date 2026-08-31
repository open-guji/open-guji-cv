# -*- coding: utf-8 -*-
"""Step2 上下版框残墨的金标标注页（`char-segmentation/column-warp` 的第二部分）。

    python scripts/build_column_border_review.py -o output/column_border_review.html

侧界行那一页定的是**竖直**方向的文字带；这一页定**水平**方向的：矫正图的
上下两端常常带进一截版框线（`column_bounds` 取页面右端 x=0 锚点，落点未必
正好压在版框上），得在 Step2 就削掉。

一列出两张卡（上端 / 下端），每张卡 = 该端的裁剪图（已清侧界行、只取文字带
宽度）+ 沿水平方向的投影曲线。人拖一条横线定「削到哪一行」，再裁决这一端属于
哪一档：

  * `clean` 版框和首字之间有间隙，线放得下（对应算法的 a 档）
  * `glued` 版框跟首字粘连，找不到间隙，只能少削一点（b 档）
  * `none`  这一端压根没有版框残墨，不用削（c 档）
  * `idk`   拿不准

金标真源是人拖的那个行数和这条裁决；投影曲线只是随卡存的快照。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "review-artifact" / "scripts"))

from open_guji_cv.utils.column_projection import (  # noqa: E402
    column_border_trim,
    column_row_profile,
    column_text_band,
    strip_column_rules,
)
from eval_column_warp import rebuild  # noqa: E402
from review_shell import render  # noqa: E402

GOLD = ROOT.parent / "open-guji-dataset" / "char-segmentation" / "column-warp" / "samples"

TITLE = "单列矫正·上下版框核校"
KEY = "column-warp-border-v1"       # 换页必须换 key
CROP_ROWS = 220                       # 每端裁多少行给人看（约 2 个字格，够看到首字）

VERDICTS = [("clean", "有间隙", "ok"), ("glued", "粘连", "zhu"),
            ("none", "没残墨", "indigo"), ("idk", "拿不准", "faint")]


def build_rows() -> tuple[list[dict], dict[str, str]]:
    rows, imgs = [], {}
    for f in sorted(GOLD.glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        warped = strip_column_rules(rebuild(s))
        band = column_text_band(warped)
        core = warped[:, band[0]:band[1]]
        prof = column_row_profile(warped, band)
        (top_px, top_case), (bot_px, bot_case) = column_border_trim(warped, band)
        h = core.shape[0]

        for end, seed, case in (("top", top_px, top_case), ("bot", bot_px, bot_case)):
            # 两端都按「从该端往里」的朝向裁，人看到的永远是"边框在上、字在下"
            crop = core[:CROP_ROWS] if end == "top" else core[h - CROP_ROWS:][::-1]
            pslice = prof[:CROP_ROWS] if end == "top" else prof[h - CROP_ROWS:][::-1]
            cid = f"{s['book']}_{s['page']}_c{s['col']}_{end}"
            ok, buf = cv2.imencode(".png", crop, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            assert ok
            imgs[cid] = "data:image/png;base64," + base64.b64encode(buf).decode()
            rows.append(dict(
                id=cid, book=s["book"], page=s["page"], col=s["col"], end=end,
                tags=s["tags"], raised=s["geometry"]["top_y_source"] == "head_raise_inner_y",
                w=int(core.shape[1]), rows=CROP_ROWS, seed=int(seed),
                # 自动判据给的档不印在卡上（会带偏人的判断），只留种子位置
                auto_case=case,
                prof=base64.b64encode(
                    bytes(int(round(float(v) * 255)) for v in pslice)).decode()))
    return rows, imgs


CSS = """
.card{background:var(--surface); border:1px solid var(--rule);
  border-left:3px solid transparent; border-radius:3px; padding:12px 13px;
  box-shadow:var(--shadow);}
""" + "".join(f'.card[data-v="{v}"]{{border-left-color:var(--{c})}}\n'
              for v, _, c in VERDICTS) + """
.card h3{margin:0; font-family:var(--serif); font-size:15px;}
.card h3 em{font-style:normal; font-family:var(--mono); font-size:11px;
  color:var(--muted); font-weight:400; margin-left:7px;}
.tags{margin:5px 0 0; display:flex; flex-wrap:wrap; gap:5px;}
.tags span{font-size:11px; padding:1px 6px; border-radius:2px;
  background:var(--sunk); color:var(--muted);}
.tags span.end{background:var(--indigo-soft); color:var(--indigo); font-weight:600;}
.tags span.raise{background:var(--ochre-soft); color:var(--ochre)}

.pair{display:flex; gap:6px; margin:10px auto 0; align-items:flex-start;}
.stage{position:relative; flex:0 1 auto; touch-action:pan-x;
  background:var(--tile); border:1px solid var(--rule-hard); border-radius:2px;
  overflow:hidden; cursor:ns-resize;}
.stage img{display:block; width:100%; height:auto; image-rendering:pixelated;}
.veil{position:absolute; left:0; right:0; top:0; background:var(--zhu);
  opacity:.3; pointer-events:none;}
.grip{position:absolute; left:0; right:0; height:2px; margin-top:-1px;
  background:var(--indigo); pointer-events:none;}
.prof{flex:0 0 54px; align-self:stretch; background:var(--ground);
  border:1px solid var(--rule); border-radius:2px;}
.prof path{fill:var(--indigo); fill-opacity:.5; stroke:none}
.prof rect.cut{fill:var(--zhu); fill-opacity:.2}

.nudge{display:flex; align-items:center; gap:6px; margin-top:9px; font-size:12px;
  color:var(--muted);}
.nudge button{min-width:36px; min-height:36px; border:1px solid var(--rule-hard);
  border-radius:3px; background:var(--surface); color:var(--ink);
  font-family:var(--mono); font-size:15px; cursor:pointer;}
.nudge button:active{background:var(--sunk)}
.nudge output{font-family:var(--mono); font-size:14px; color:var(--ink);
  min-width:2.4em; text-align:center; font-variant-numeric:tabular-nums;}
.nudge .rst{margin-left:auto; min-width:0; padding:0 9px; font-size:11px;
  font-family:var(--sans); color:var(--muted);}

.verdicts{display:grid; grid-template-columns:repeat(NCOL,1fr); gap:6px; margin-top:10px;}
.verdicts button{min-height:44px; border:1px solid var(--rule-hard); border-radius:3px;
  background:var(--surface); color:var(--ink); font-family:var(--sans);
  font-size:13px; font-weight:500; cursor:pointer;}
.verdicts button:active{background:var(--sunk)}
.verdicts button:focus-visible{outline:2px solid var(--indigo); outline-offset:2px;}
.verdicts button[aria-pressed="true"]{color:var(--on-solid); border-color:transparent;}
""".replace("NCOL", str(len(VERDICTS))) + "".join(
    f'.verdicts button.{v}[aria-pressed="true"]{{background:var(--{c})}}\n'
    for v, _, c in VERDICTS)


PAGE_JS = r"""
const VERDICTS = __VERDICTS__;

const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span>
  <span class="save" id="save">本机</span>
  <span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open>
    <summary>怎么标</summary>
    <p>一张卡是<b>一列的一端</b>（上端或下端）。图已经把两侧界行清掉了、只留文字带那一段宽度，
       并且<b>一律转成「版框在上、字在下」</b>——下端的卡是翻过来给你看的，别被字倒了吓到。
       右边那条是<b>沿水平方向的投影</b>：每一行的墨占比。</p>
    <p>拖那条蓝线，定出<b>要削掉几行</b>（红色阴影就是会被抹白的部分）。
       目标是：<b>版框墨全在线以上，字身墨一点不碰</b>。不用削就拖到 0。</p>
    <div class="rubric">
      <div><b style="background:var(--ok-soft);color:var(--ok)">有间隙</b>
        <span>版框和首字之间看得到空白，线能干净地放进去。</span></div>
      <div><b style="background:var(--zhu-soft);color:var(--zhu)">粘连</b>
        <span>版框跟首字连着，找不到间隙——线只能少削一点，宁可留残框也别切字。</span></div>
      <div><b style="background:var(--indigo-soft);color:var(--indigo)">没残墨</b>
        <span>这一端根本没带进版框，什么都不用削（线放 0）。</span></div>
      <div><b style="background:var(--sunk);color:var(--faint)">拿不准</b>
        <span>看不清，或这一端另有毛病。</span></div>
    </div>
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
  <h2>标注结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea>
  <div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div>
</div></div>`;

const rowId = r => r.id;
/* page_js 整段跑在壳之前，`D` 还在暂时性死区里——索引必须懒建 */
let _idx = null;
const rowOf = id => (_idx || (_idx = Object.fromEntries(D.rows.map(r => [r.id, r]))))[id];

const trimKey = id => id + '#trim';
function trimOf(id){
  const raw = (state[trimKey(id)] || {}).v;
  const v = raw === undefined ? NaN : Number(raw);
  return Number.isFinite(v) ? v : rowOf(id).seed;
}
function setTrim(id, v){
  const r = rowOf(id);
  const n = Math.max(0, Math.min(Math.round(v), r.rows));
  state[trimKey(id)] = {v: String(n), t: Date.now()};
  persist();
  return n;
}
const touched = id => !!state[trimKey(id)];

function unpackProf(s){
  const bin = atob(s), out = new Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i) / 255;
  return out;
}

function profSvg(r){
  const p = unpackProf(r.prof), n = p.length;
  /* 横躺的投影：y 是行号（跟左边的图对齐），x 是墨占比。按本卡峰值归一。 */
  const pmax = Math.max(...p, 0.02);
  let d = 'M0,0';
  for (let i = 0; i < n; i++){ const x = p[i] / pmax * 96;
    d += ` L${x},${i} L${x},${i + 1}`; }
  d += ` L0,${n} Z`;
  return `<svg class="prof" viewBox="0 0 100 ${n}" preserveAspectRatio="none">
    <rect class="cut" x="0" y="0" width="100" height="0"></rect>
    <path d="${d}"></path></svg>`;
}

function card(r){
  const v = verdictOf(r.id), t = trimOf(r.id);
  const btn = ([k, txt]) => `<button class="${k}" data-v="${k}" aria-pressed="${v === k}">${txt}</button>`;
  const tag = s => `<span>${esc(s)}</span>`;
  return `<article class="card" data-id="${r.id}"${v ? ` data-v="${v}"` : ''}>
    <h3>${r.book}/${r.page} 第 ${r.col} 列<em>${r.end === 'top' ? '上端' : '下端（已翻转）'}</em></h3>
    <div class="tags"><span class="end">${r.end === 'top' ? '上' : '下'}</span>${
      r.raised && r.end === 'top' ? '<span class="raise">抬头列</span>' : ''}${
      r.tags.map(tag).join('')}${touched(r.id) ? '<span>已改过</span>' : ''}</div>
    <div class="pair" style="max-width:${r.w * 2 + 60}px">
      <div class="stage" style="flex-basis:${r.w * 2}px">
        <img data-src="${r.id}" alt="">
        <div class="veil"></div><div class="grip"></div>
      </div>
      ${profSvg(r)}
    </div>
    <div class="nudge">
      <button data-n="-5">−5</button><button data-n="-1">−</button>
      <output>${t}</output>
      <button data-n="1">+</button><button data-n="5">+5</button>
      <span>行</span><button class="rst" data-n="reset">复位</button>
    </div>
    <div class="verdicts">${VERDICTS.map(btn).join('')}</div>
  </article>`;
}

function paint(art){
  const r = rowOf(art.dataset.id), t = trimOf(r.id), pct = t / r.rows * 100;
  art.querySelector('.veil').style.height = pct + '%';
  art.querySelector('.grip').style.top = pct + '%';
  art.querySelector('output').textContent = t;
  art.querySelector('.prof rect.cut').setAttribute('height', t);
}
function paintAll(){ listEl.querySelectorAll('.card').forEach(paint); }

let drag = null;
function yOf(e, stage, r){
  const box = stage.getBoundingClientRect();
  return Math.max(0, Math.min(r.rows, (e.clientY - box.top) / box.height * r.rows));
}
document.addEventListener('pointerdown', e => {
  const stage = e.target.closest('.stage'); if (!stage) return;
  const art = stage.closest('.card'), r = rowOf(art.dataset.id);
  drag = {art, stage, r};
  stage.setPointerCapture(e.pointerId);
  move(e);
});
function move(e){
  if (!drag) return;
  setTrim(drag.r.id, yOf(e, drag.stage, drag.r));
  paint(drag.art);
  e.preventDefault();
}
document.addEventListener('pointermove', move);
document.addEventListener('pointerup', () => { drag = null; });
document.addEventListener('pointercancel', () => { drag = null; });

document.addEventListener('click', e => {
  const nb = e.target.closest('.nudge button');
  if (nb){
    const art = nb.closest('.card'), r = rowOf(art.dataset.id);
    if (nb.dataset.n === 'reset') { state[trimKey(r.id)] = {v: String(r.seed), t: Date.now()}; persist(); }
    else setTrim(r.id, trimOf(r.id) + Number(nb.dataset.n));
    paint(art); return;
  }
  const fb = e.target.closest('#filter button'); if (!fb) return;
  filter = fb.dataset.f;
  [...fb.parentElement.children].forEach(x => x.setAttribute('aria-pressed', String(x === fb)));
  draw(); paintAll();
});

let filter = 'todo';
function visibleRows(){
  if (filter === 'all') return D.rows;
  const done = filter === 'done';
  return D.rows.filter(r => !!verdictOf(r.id) === done);
}
function afterVerdict(){ if (filter !== 'all') draw(); paintAll(); }

function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r =>
    JSON.stringify({id: r.id, book: r.book, page: r.page, col: r.col, end: r.end,
                     verdict: verdictOf(r.id), trim: trimOf(r.id),
                     seed: r.seed, moved: touched(r.id)})).join('\n');
}

/* 壳在整段脚本的最后才第一次 draw()，初次补画排到宏任务里 */
setTimeout(paintAll, 0);
""".replace("__VERDICTS__", json.dumps([[v, t] for v, t, _ in VERDICTS], ensure_ascii=False)) \
   .replace("__TITLE__", TITLE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="output/column_border_review.html")
    ap.add_argument("--cards", default="output/column_border_cards.jsonl")
    args = ap.parse_args()

    rows, imgs = build_rows()
    cards = Path(args.cards)
    cards.parent.mkdir(parents=True, exist_ok=True)
    cards.write_text("\n".join(
        json.dumps({k: v for k, v in r.items() if k != "prof"}, ensure_ascii=False)
        for r in rows) + "\n", encoding="utf-8")

    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS,
                   payload={"rows": rows, "imgs": imgs})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{len(rows)} 张卡（{len(rows) // 2} 列 × 上下两端）-> {out} "
          f"({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
