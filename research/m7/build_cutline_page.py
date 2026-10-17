# -*- coding: utf-8 -*-
"""M7 块 C2：彝六字形「上/中/下」切线标注页（给用户点）。壳用 skill review-artifact 的 review_shell。

    python research/m7/build_cutline_page.py <yi_560 目录> <out.html> [--cards cards.jsonl]

<yi_560 目录> = dataset 分支 claude/Evan-1011 的 char-groups/variant/yi_560（要有 crops/、user_parts_labels.jsonl）。
每张卡一个字块图：点两下放两条横线（上/中、中/下），拖动可调，再点一下移动离得近的那条。
裁决值 `cut:<y1>,<y2>`（0–1，占图高的比例，自上而下）；`idk`＝看不清；`bad`＝这图不是这类字/切坏了。
卡的 id 与顺序冻在 --cards（JSONL），重建页面时照读，别让 id 漂。
"""
from __future__ import annotations

import base64, io, json, sys
from pathlib import Path

SHELL = Path(__file__).resolve().parents[2] / ".claude/skills/review-artifact/scripts"
sys.path.insert(0, str(SHELL))
from review_shell import render  # noqa: E402

TITLE = "彝组切线标注"
KEY = "m7-yi560-cutline-v1"

CSS = """
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:12px 13px;box-shadow:var(--shadow)}
.card[data-v^="cut"]{border-left-color:var(--ok)}
.card[data-v="idk"]{border-left-color:var(--faint)}
.card[data-v="bad"]{border-left-color:var(--zhu)}
.card h3{margin:0;font-family:var(--serif);font-size:15px}
.card p{margin:6px 0 0;font-size:13px;color:var(--muted)}
.cv{position:relative;display:inline-block;margin-top:10px;touch-action:none;user-select:none;-webkit-user-select:none;background:var(--tile)}
.cv img{display:block;width:260px;max-width:100%;image-rendering:pixelated}
.cv .ln{position:absolute;left:0;right:0;height:0;border-top:2px solid var(--zhu);pointer-events:none}
.cv .ln::after{content:attr(data-t);position:absolute;right:2px;top:-18px;font-size:12px;color:var(--zhu);background:var(--surface);padding:0 3px;border-radius:2px}
.verdicts{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}
.verdicts button,.redo{min-height:44px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-family:var(--sans);font-size:13px;font-weight:500;cursor:pointer}
.verdicts button[aria-pressed="true"]{color:var(--on-solid);border-color:transparent}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
.verdicts button.bad[aria-pressed="true"]{background:var(--zhu)}
.redo{width:100%;margin-top:6px}
"""

PAGE_JS = r"""
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span><span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open><summary>怎么点</summary>
    <p>每张图是一个“彝”类字块，要把它从上到下切成三段：上（彑/彐）、中（米+糸 或 米+分）、下（廾 或 大）。
       在图上<b>点两下</b>放两条横线：第一条在上/中之间，第二条在中/下之间；线可以拖，再点一下会移动离得近的那条。
       图不对或看不清就点下面的按钮。每张卡下面写着你之前标的三段读法，仅供对照。结果自动存回本页。</p></details>
  <div class="ctrl">
    <div class="seg" id="filter"><button data-f="todo" aria-pressed="true">未点</button>
      <button data-f="all" aria-pressed="false">全部</button><button data-f="done" aria-pressed="false">已点</button></div>
    <button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
  <div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea><div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div></div></div>`;

const rowId = r => r.id;
const cutOf = id => { const v = verdictOf(id); if (!v.startsWith('cut:')) return []; return v.slice(4).split(',').map(Number); };
function lines(cs){ return cs.map((y,i)=>`<i class="ln" data-t="${i?'中/下':'上/中'}" style="top:${(y*100).toFixed(2)}%"></i>`).join(''); }
function card(r){
  const v = verdictOf(r.id), cs = cutOf(r.id);
  const btn = ([k,t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v.split(':')[0]}"`:''}>
    <h3>${esc(r.title)}</h3><p>${esc(r.note)}</p>
    <div class="cv" data-id="${r.id}"><img data-src="${r.img}" alt="">${lines(cs)}</div>
    <button class="redo" data-redo="${r.id}">重新点（清掉这张的线）</button>
    <div class="verdicts">${[['idk','看不清'],['bad','图不对']].map(btn).join('')}<span></span></div></article>`;
}
let filter = 'todo';
function visibleRows(){ if (filter==='all') return D.rows; const done = filter==='done'; return D.rows.filter(r => !!verdictOf(r.id) === done); }
document.addEventListener('click', e => {
  const b = e.target.closest('#filter button');
  if (b){ filter = b.dataset.f; [...b.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===b))); draw(); return; }
  const rd = e.target.closest('.redo');
  if (rd){ const id = rd.dataset.redo; delete state[id]; persist(); draw(); }
});
function afterVerdict(){ if (filter !== 'all') draw(); }

/* 在图上点/拖：state[id] = {v:'cut:y1,y2', t} */
let drag = null;
function yOf(cv, ev){ const r = cv.getBoundingClientRect(); return Math.min(0.98, Math.max(0.02, (ev.clientY - r.top) / r.height)); }
function setCuts(cv, cs){
  const id = cv.dataset.id; cs = cs.slice().sort((a,b)=>a-b);
  cv.querySelectorAll('.ln').forEach(n=>n.remove());
  cv.insertAdjacentHTML('beforeend', lines(cs));
  const art = cv.closest('.card');
  if (cs.length === 2){ state[id] = {v:'cut:'+cs.map(y=>y.toFixed(3)).join(','), t:Date.now()}; art.dataset.v='cut';
    art.querySelectorAll('.verdicts button').forEach(x=>x.setAttribute('aria-pressed','false')); }
  else { state[id] = {v:'cut:'+cs.map(y=>y.toFixed(3)).join(','), t:Date.now()}; }
  if (cs.length < 2) { /* 只放了一条：还不算完成 */ delete state[id]; art.removeAttribute('data-v'); cv._half = cs; }
  else cv._half = null;
}
document.addEventListener('pointerdown', e => {
  const cv = e.target.closest('.cv'); if (!cv) return;
  e.preventDefault(); cv.setPointerCapture && cv.setPointerCapture(e.pointerId);
  const id = cv.dataset.id; let cs = cv._half || cutOf(id); const y = yOf(cv, e);
  if (cs.length < 2){ cs = cs.concat([y]); drag = null; setCuts(cv, cs); if (cs.length===2) persist(); tally(); return; }
  const k = Math.abs(cs[0]-y) <= Math.abs(cs[1]-y) ? 0 : 1; cs[k] = y; drag = {cv, k, cs}; setCuts(cv, cs);
});
document.addEventListener('pointermove', e => { if (!drag) return; drag.cs[drag.k] = yOf(drag.cv, e); setCuts(drag.cv, drag.cs); });
document.addEventListener('pointerup', () => { if (!drag) return; drag = null; persist(); tally(); });

function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => {
    const v = verdictOf(r.id), cs = cutOf(r.id);
    return JSON.stringify({id:r.id, verdict: cs.length?'cut':v, y1: cs[0]??null, y2: cs[1]??null});
  }).join('\n');
}
""".replace("__TITLE__", TITLE)


def main() -> None:
    d, out = Path(sys.argv[1]), Path(sys.argv[2])
    cards_path = Path(sys.argv[sys.argv.index("--cards") + 1]) if "--cards" in sys.argv else None
    labels = {}
    for line in (d / "user_parts_labels.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line); labels[r["id"]] = r
    if cards_path and cards_path.exists():
        ids = [json.loads(l)["id"] for l in cards_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        ids = sorted(labels, key=lambda i: (labels[i]["target"], i))
        if cards_path:
            cards_path.write_text("".join(json.dumps({"id": i}, ensure_ascii=False) + "\n" for i in ids), encoding="utf-8")
    rows, imgs = [], {}
    for i in ids:
        lb = labels[i]; fn = i.replace(":", "_") + ".png"
        imgs[i] = "data:image/png;base64," + base64.b64encode((d / "crops" / fn).read_bytes()).decode()
        rows.append({"id": i, "img": i, "title": f"{i}",
                     "note": f"你之前标的读法：上 {lb['top']}　中 {lb['mid']}　下 {lb['bot']}"})
    html = render(TITLE, KEY, verdicts={}, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB  {len(rows)} 卡")


if __name__ == "__main__":
    main()
