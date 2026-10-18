# -*- coding: utf-8 -*-
"""M7 IDS 扩展：「字形 + 一条切线」标注页（给用户点）。壳用 skill review-artifact 的 review_shell。

    python research/m7/ids2/build_form_cut_page.py <cfg: shen|can> <cells.jsonl> <crops_dir> <out.html> [--done done.jsonl]

cells.jsonl 每行 {"id","hint"(整理本字,仅供参考),"pre"(机器预画折线,可无)}。顺序冻在文件里，别让 id 漂。
每张卡：选字形（按钮）→ 画/采纳一条切线。裁决值 `{"f":字形,"p":[[x,y],…]}` 的 JSON；f 为 `?`(看不清)/`x`(其他字) 时不要线。
切线：h＝水平折线，点从左到右（上/下分界）；v＝竖直折线，点从上到下（左/右分界）。坐标 0–1，左上原点。
"""
from __future__ import annotations

import base64, io, json, sys
from pathlib import Path

import numpy as np
from PIL import Image

SHELL = Path(__file__).resolve().parents[3] / ".claude/skills/review-artifact/scripts"
sys.path.insert(0, str(SHELL))
from review_shell import render  # noqa: E402

CFG = {
    "shen": dict(title="慎愼 字形与切线", key="m7-ids2-shen-v1", orient="v", forms=["愼", "慎"],
                 cut_hint="竖线：把左边的竖心旁（忄）和右边的「真/眞」分开。沿分界线从上到下点点。",
                 form_hint="右半是「眞」（上面匕，中间目，下面八）选愼；右半是「真」（上面十，下面具）选慎。"),
    "can": dict(title="參㕘 字形与切线", key="m7-ids2-can-v1", orient="h", forms=["參", "㕘"],
                cut_hint="横线：把上面的「厽」和下面的部分分开。沿分界线从左到右点点。",
                form_hint="下半是三撇（彡）选參；下半是「小」形（尒）选㕘。"),
}

CSS = """
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:12px 13px;box-shadow:var(--shadow)}
.card[data-v="ok"]{border-left-color:var(--ok)}
.card[data-v="skip"]{border-left-color:var(--faint)}
.card h3{margin:0;font-family:var(--serif);font-size:15px}
.card p{margin:6px 0 0;font-size:13px;color:var(--muted)}
.cv{position:relative;display:block;margin-top:10px;touch-action:none;user-select:none;-webkit-user-select:none;background:var(--tile);cursor:crosshair;width:280px;max-width:100%;aspect-ratio:1/1}
.cv img{display:block;width:100%;height:100%;object-fit:fill;image-rendering:pixelated}
.cv svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.cv .pl{fill:none;stroke:#e0412f;stroke-width:2;vector-effect:non-scaling-stroke}
.cv .dot{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.5);background:#e0412f}
.row2{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}
.row2 button,.tools button{min-height:44px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-family:var(--serif);font-size:18px;font-weight:500;cursor:pointer}
.row2 button.sm{font-family:var(--sans);font-size:13px}
.row2 button[aria-pressed="true"]{background:var(--indigo);color:var(--on-solid);border-color:transparent}
.row2 button.sm[aria-pressed="true"]{background:var(--faint)}
.tools{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px}
.tools button{font-family:var(--sans);font-size:13px}
.tools .adopt{grid-column:1/-1;background:var(--ok-soft);border-color:var(--ok)}
"""

PAGE_JS = r"""
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span><span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open><summary>怎么点</summary>
    <p>每张图两步：①选这个字是什么（<b>以图上刻的为准</b>，「整理本」只是参考，可能不对）；②画一条切线。__FORMHINT__ __CUTHINT__
       红线是机器画的初稿，对就点「采纳」，不对就拖红点或点出新的点（至少 2 个点）。字不是这一组的字点「其他字」，看不清点「看不清」，这两种不用画线。点完自动存回本页。</p></details>
  <div class="ctrl">
    <div class="seg" id="filter"><button data-f="todo" aria-pressed="true">未标</button>
      <button data-f="all" aria-pressed="false">全部</button><button data-f="done" aria-pressed="false">已标</button></div>
    <button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
  <div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea><div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div></div></div>`;

const rowId = r => r.id;
const isH = () => D.orient === 'h';
const cur = {};          /* 编辑中的值 {f, p}，没提交前不进 state */
function val(id){
  if (cur[id]) return cur[id];
  const v = verdictOf(id), row = D.rows.find(r => r.id === id);
  let o = {f:'', p:[]};
  if (v){ try { o = JSON.parse(v); } catch(e){} }
  else if (row && row.pre) o = {f:'', p: JSON.parse(JSON.stringify(row.pre)), pre:true};
  return cur[id] = o;
}
const SKIP = ['?','x'];
const complete = id => { const o = val(id); return !!o.f && (SKIP.includes(o.f) || (o.p.length >= 2 && !o.pre)); };
function overlay(id){
  const o = val(id), p = SKIP.includes(o.f) ? [] : o.p;
  if (p.length < 1) return '';
  const ext = isH() ? [[0,p[0][1]],...p,[1,p[p.length-1][1]]] : [[p[0][0],0],...p,[p[p.length-1][0],1]];
  const line = p.length < 2 ? '' : `<polyline class="pl" points="${ext.map(q=>(q[0]*100).toFixed(2)+','+(q[1]*100).toFixed(2)).join(' ')}"/>`;
  const dots = p.map((q,i)=>`<i class="dot" data-i="${i}" style="left:${(q[0]*100).toFixed(2)}%;top:${(q[1]*100).toFixed(2)}%"></i>`).join('');
  return `<svg viewBox="0 0 100 100" preserveAspectRatio="none">${line}</svg>${dots}`;
}
function card(r){
  const o = val(r.id), done = complete(r.id);
  const fb = D.forms.map(f => `<button data-f="${f}" aria-pressed="${o.f===f}">${f}</button>`).join('')
    + `<button class="sm" data-f="x" aria-pressed="${o.f==='x'}">其他字</button><button class="sm" data-f="?" aria-pressed="${o.f==='?'}">看不清</button>`;
  const showAdopt = o.pre && !SKIP.includes(o.f);
  return `<article class="card" data-id="${r.id}"${done?` data-v="${SKIP.includes(o.f)?'skip':'ok'}"`:''}>
    <h3>${esc(r.id)}</h3><p>${esc(r.note)}</p>
    <div class="cv" data-id="${r.id}"><img data-src="${r.id}" alt="">${overlay(r.id)}</div>
    <div class="row2">${fb}</div>
    <div class="tools">${showAdopt?`<button class="adopt" data-adopt="${r.id}">✓ 红线对，采纳</button>`:''}
      <button data-undo="${r.id}">撤销上一点</button><button data-clear="${r.id}">线重画</button></div></article>`;
}
let filter = 'todo';
function visibleRows(){ if (filter==='all') return D.rows; const d = filter==='done'; return D.rows.filter(r => !!verdictOf(r.id) === d); }
function commit(id){
  const o = val(id);
  if (complete(id)){ const out = {f:o.f, p: SKIP.includes(o.f) ? [] : o.p.map(q=>q.map(x=>+x.toFixed(4)))};
    state[id] = {v: JSON.stringify(out), t: Date.now()}; }
  else if (verdictOf(id)) delete state[id];
  persist(); tally();
}
function redraw(id){
  const art = document.querySelector(`.card[data-id="${CSS.escape(id)}"]`); if (!art) return;
  const r = D.rows.find(x => x.id === id); const tmp = document.createElement('div'); tmp.innerHTML = card(r);
  const n = tmp.firstElementChild; n.querySelector('img').src = art.querySelector('img').src; art.replaceWith(n);
}
document.addEventListener('click', e => {
  const f = e.target.closest('#filter button');
  if (f){ filter = f.dataset.f; [...f.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===f))); draw(); return; }
  const b = e.target.closest('.row2 button');
  if (b){ const id = b.closest('.card').dataset.id, o = val(id); o.f = o.f === b.dataset.f ? '' : b.dataset.f; commit(id); redraw(id); return; }
  const ad = e.target.closest('[data-adopt]');
  if (ad){ const id = ad.dataset.adopt, o = val(id); delete o.pre; commit(id); redraw(id); return; }
  const u = e.target.closest('[data-undo]');
  if (u){ const id = u.dataset.undo, o = val(id); o.p.pop(); delete o.pre; commit(id); redraw(id); return; }
  const c = e.target.closest('[data-clear]');
  if (c){ const id = c.dataset.clear, o = val(id); o.p = []; delete o.pre; commit(id); redraw(id); }
});
function afterVerdict(){ if (filter !== 'all') draw(); }
let drag = null;
function pos(cv, ev){ const r = cv.getBoundingClientRect();
  return [Math.min(1,Math.max(0,(ev.clientX-r.left)/r.width)), Math.min(1,Math.max(0,(ev.clientY-r.top)/r.height))]; }
const sortP = p => p.sort((a,b)=> isH() ? a[0]-b[0] : a[1]-b[1]);
function repaint(cv, id){ cv.querySelectorAll('svg,.dot').forEach(n=>n.remove()); cv.insertAdjacentHTML('beforeend', overlay(id)); }
document.addEventListener('pointerdown', e => {
  const cv = e.target.closest('.cv'); if (!cv) return;
  e.preventDefault(); const id = cv.dataset.id, o = val(id);
  if (SKIP.includes(o.f)) o.f = '';
  const dot = e.target.closest('.dot');
  if (dot){ drag = {cv, id, i:+dot.dataset.i}; return; }
  if (o.pre){ o.p = []; delete o.pre; }
  const q = pos(cv, e); o.p.push(q); sortP(o.p); drag = {cv, id, i:o.p.indexOf(q)}; repaint(cv, id);
});
document.addEventListener('pointermove', e => {
  if (!drag) return; const o = val(drag.id); o.p[drag.i] = pos(drag.cv, e); delete o.pre; repaint(drag.cv, drag.id);
});
document.addEventListener('pointerup', () => {
  if (!drag) return; const id = drag.id, o = val(id); delete o.pre; sortP(o.p); drag = null; commit(id); redraw(id);
});
function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => JSON.stringify({id:r.id, ...JSON.parse(verdictOf(r.id))})).join('\n');
}
"""


def main() -> None:
    cfg = CFG[sys.argv[1]]
    cells, crops, out = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    done = {}
    if "--done" in sys.argv:
        for line in Path(sys.argv[sys.argv.index("--done") + 1]).read_text(encoding="utf-8").splitlines():
            r = json.loads(line); done[r["id"]] = {"v": json.dumps({"f": r["f"], "p": r["p"]}, ensure_ascii=False), "t": 0}
    rows, imgs = [], {}
    for line in cells.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line); i = c["id"]
        im = Image.open(crops / (i.replace(":", "_") + ".png")).convert("L").resize((128, 128), Image.BILINEAR)
        im = Image.fromarray((np.asarray(im) // 16 * 17).astype(np.uint8))
        b = io.BytesIO(); im.save(b, "PNG", optimize=True)
        imgs[i] = "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
        rows.append({"id": i, **({"pre": c["pre"]} if c.get("pre") else {}),
                     "note": f"整理本：{c.get('hint') or '—'}（仅供参考）"})
    js = (PAGE_JS.replace("__TITLE__", cfg["title"]).replace("__FORMHINT__", cfg["form_hint"]).replace("__CUTHINT__", cfg["cut_hint"]))
    html = render(cfg["title"], cfg["key"], verdicts=done, css=CSS, page_js=js,
                  payload={"rows": rows, "imgs": imgs, "orient": cfg["orient"], "forms": cfg["forms"]})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB  {len(rows)} 卡")


if __name__ == "__main__":
    main()
