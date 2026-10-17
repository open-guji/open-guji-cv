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

TITLE = "彝组折线标注"
KEY = "m7-yi560-polyline-v2"      # v1 是直线版，作废

CSS = """
.card{background:var(--surface);border:1px solid var(--rule);border-left:3px solid transparent;border-radius:3px;padding:12px 13px;box-shadow:var(--shadow)}
.card[data-v="poly"]{border-left-color:var(--ok)}
.card[data-v="idk"]{border-left-color:var(--faint)}
.card[data-v="bad"]{border-left-color:var(--zhu)}
.card h3{margin:0;font-family:var(--serif);font-size:15px}
.card p{margin:6px 0 0;font-size:13px;color:var(--muted)}
.cv{position:relative;display:inline-block;margin-top:10px;touch-action:none;user-select:none;-webkit-user-select:none;background:var(--tile);cursor:crosshair}
.cv img{display:block;width:280px;max-width:100%;image-rendering:pixelated}
.cv svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.cv .pl{fill:none;stroke-width:2;vector-effect:non-scaling-stroke}
.cv .pl.b0{stroke:#e0412f}.cv .pl.b1{stroke:#2f6fe0}
.cv .dot{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.5)}
.cv .dot.b0{background:#e0412f}.cv .dot.b1{background:#2f6fe0}
.seg2{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.seg2 button,.tools button,.verdicts button{min-height:44px;border:1px solid var(--rule-hard);border-radius:3px;background:var(--surface);color:var(--ink);font-family:var(--sans);font-size:13px;font-weight:500;cursor:pointer}
.seg2 button[aria-pressed="true"]{color:#fff;border-color:transparent}
.seg2 button.b0[aria-pressed="true"]{background:#e0412f}.seg2 button.b1[aria-pressed="true"]{background:#2f6fe0}
.tools{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px}
.verdicts{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-top:6px}
.verdicts button[aria-pressed="true"]{color:var(--on-solid);border-color:transparent}
.verdicts button.idk[aria-pressed="true"]{background:var(--faint)}
.verdicts button.bad[aria-pressed="true"]{background:var(--zhu)}
"""

PAGE_JS = r"""
const BODY = `
<header class="top"><div class="top-in">
  <span class="brand">__TITLE__</span><span class="save" id="save">本机</span><span class="count" id="count">0 / 0</span>
</div><div class="bar"><i id="prog"></i></div></header>
<div class="wrap">
  <details class="intro" id="intro" open><summary>怎么点（折线）</summary>
    <p>把每个字块从上到下分成三段：上（彑/彐）、中（米+糸 或 米+分）、下（廾 或 大）。
       每张图要画<b>两条分界折线</b>：红色＝上/中之间，蓝色＝中/下之间。先选好当前要画哪一条，
       然后<b>沿着分界线从左到右一个点一个点地点</b>（至少 2 个点，笔画有上下残留的地方多点几个）；点可以<b>拖动</b>。
       点错了用「撤销上一点」。两条线都有 2 个以上的点就算这张完成，自动存回本页。图不对或看不清点下面的按钮。
       线两端会自动延伸到图的左右边缘。</p></details>
  <div class="ctrl">
    <div class="seg" id="filter"><button data-f="todo" aria-pressed="true">未画</button>
      <button data-f="all" aria-pressed="false">全部</button><button data-f="done" aria-pressed="false">已画</button></div>
    <button class="ghost" id="copy">复制</button><button class="ghost" id="reset">清空</button></div>
  <div class="list" id="list"></div></div>
<div class="sheet" id="sheet" hidden><div class="sheet-in"><h2>结果</h2><p id="sheet-note"></p>
  <textarea id="sheet-text" readonly></textarea><div class="row"><button class="ghost" id="sheet-copy">复制</button>
  <button class="ghost" id="sheet-close">关闭</button></div></div></div>`;

const rowId = r => r.id;
/* 折线数据：pl[id] = [[[x,y],...],[[x,y],...]]，x、y 都是 0–1 的比例（左上原点）。完成后写进 state[id].v = 'poly:'+JSON */
const pl = {}, act = {};
function plOf(id){
  if (pl[id]) return pl[id];
  const v = verdictOf(id);
  const row = D.rows.find(r => r.id === id);
  pl[id] = v.startsWith('poly:') ? JSON.parse(v.slice(5)) : (row && row.pre ? JSON.parse(JSON.stringify(row.pre)) : [[],[]]);  /* pre：旧直线版的预填，用户碰一下才算数 */
  return pl[id];
}
const complete = id => { const p = plOf(id); return p[0].length >= 2 && p[1].length >= 2; };
function overlay(id){
  const p = plOf(id), a = act[id] ?? 0;
  const svg = p.map((pts,k)=> pts.length<2 ? '' :
    `<polyline class="pl b${k}" points="${[[0,pts[0][1]],...pts,[1,pts[pts.length-1][1]]].map(q=>(q[0]*100).toFixed(2)+','+(q[1]*100).toFixed(2)).join(' ')}"/>`).join('');
  const dots = p.map((pts,k)=>pts.map((q,i)=>`<i class="dot b${k}" data-k="${k}" data-i="${i}" style="left:${(q[0]*100).toFixed(2)}%;top:${(q[1]*100).toFixed(2)}%"></i>`).join('')).join('');
  return `<svg viewBox="0 0 100 100" preserveAspectRatio="none">${svg}</svg>${dots}`;
}
function card(r){
  const v = verdictOf(r.id), a = act[r.id] ?? 0;
  const btn = ([k,t]) => `<button class="${k}" data-v="${k}" aria-pressed="${v===k}">${t}</button>`;
  return `<article class="card" data-id="${r.id}"${v?` data-v="${v.split(':')[0]}"`:''}>
    <h3>${esc(r.title)}</h3><p>${esc(r.note)}</p>
    <div class="seg2"><button class="b0" data-act="0" aria-pressed="${a===0}">① 画 上/中 线（红）</button>
      <button class="b1" data-act="1" aria-pressed="${a===1}">② 画 中/下 线（蓝）</button></div>
    <div class="cv" data-id="${r.id}"><img data-src="${r.img}" alt="">${overlay(r.id)}</div>
    ${r.auto && !v ? `<div class="tools"><button data-adopt="${r.id}" style="grid-column:1/-1;background:var(--ok-soft);border-color:var(--ok)">✓ 机器画得对，采纳</button></div>` : ''}
    <div class="tools"><button data-undo="${r.id}">撤销当前线的上一点</button><button data-clear="${r.id}">这张全部重画</button></div>
    <div class="verdicts">${[['idk','看不清'],['bad','图不对']].map(btn).join('')}</div></article>`;
}
let filter = 'todo';
function visibleRows(){ if (filter==='all') return D.rows; const done = filter==='done'; return D.rows.filter(r => !!verdictOf(r.id) === done); }
function commit(id){
  const art = document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);
  const cv = document.querySelector(`.cv[data-id="${CSS.escape(id)}"]`);
  if (cv){ cv.querySelectorAll('svg,.dot').forEach(n=>n.remove()); cv.insertAdjacentHTML('beforeend', overlay(id)); }
  if (complete(id)){ state[id] = {v:'poly:'+JSON.stringify(plOf(id).map(a=>a.map(q=>q.map(x=>+x.toFixed(4))))), t:Date.now()};
    if (art){ art.dataset.v='poly'; art.querySelectorAll('.verdicts button').forEach(x=>x.setAttribute('aria-pressed','false')); } }
  else if (verdictOf(id).startsWith('poly:')){ delete state[id]; if (art) art.removeAttribute('data-v'); }
  persist(); tally();
}
document.addEventListener('click', e => {
  const f = e.target.closest('#filter button');
  if (f){ filter = f.dataset.f; [...f.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===f))); draw(); return; }
  const a = e.target.closest('.seg2 button');
  if (a){ const id = a.closest('.card').dataset.id; act[id] = +a.dataset.act; [...a.parentElement.children].forEach(x=>x.setAttribute('aria-pressed',String(x===a))); return; }
  const ad = e.target.closest('[data-adopt]');
  if (ad){ commit(ad.dataset.adopt); draw(); return; }
  const u = e.target.closest('[data-undo]');
  if (u){ const id = u.dataset.undo, p = plOf(id), k = act[id] ?? 0; p[k].pop(); commit(id); return; }
  const c = e.target.closest('[data-clear]');
  if (c){ const id = c.dataset.clear; pl[id] = [[],[]]; if (verdictOf(id).startsWith('poly:')) delete state[id]; commit(id); draw(); }
});
function afterVerdict(){ if (filter !== 'all') draw(); }

let drag = null;
function pos(cv, ev){ const r = cv.getBoundingClientRect();
  return [Math.min(1,Math.max(0,(ev.clientX-r.left)/r.width)), Math.min(0.99,Math.max(0.01,(ev.clientY-r.top)/r.height))]; }
document.addEventListener('pointerdown', e => {
  const cv = e.target.closest('.cv'); if (!cv) return;
  e.preventDefault(); const id = cv.dataset.id, p = plOf(id);
  const dot = e.target.closest('.dot');
  if (dot){ drag = {cv, id, k:+dot.dataset.k, i:+dot.dataset.i}; return; }
  const k = act[id] ?? 0, q = pos(cv, e);
  p[k].push(q); p[k].sort((a,b)=>a[0]-b[0]);                 // 按 x 排序：折线从左到右
  drag = {cv, id, k, i:p[k].indexOf(q)}; commit(id);
});
document.addEventListener('pointermove', e => {
  if (!drag) return;
  const p = plOf(drag.id), q = pos(drag.cv, e); p[drag.k][drag.i] = q;
  const ov = drag.cv; ov.querySelectorAll('svg,.dot').forEach(n=>n.remove()); ov.insertAdjacentHTML('beforeend', overlay(drag.id));
});
document.addEventListener('pointerup', () => {
  if (!drag) return; const id = drag.id, p = plOf(id);
  p.forEach(a=>a.sort((x,y)=>x[0]-y[0])); drag = null; commit(id);
});

function payload(){
  return D.rows.filter(r => verdictOf(r.id)).map(r => {
    const v = verdictOf(r.id);
    return JSON.stringify(v.startsWith('poly:') ? {id:r.id, verdict:'poly', upper_mid: JSON.parse(v.slice(5))[0], mid_lower: JSON.parse(v.slice(5))[1]} : {id:r.id, verdict:v});
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
    pre = {}
    if "--prefill" in sys.argv:       # 旧直线版裁决 `cut:y1,y2` → 预填成两条两点折线（用户修改后才算完成）
        for line in Path(sys.argv[sys.argv.index("--prefill") + 1]).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if str(r.get("verdict", "")).startswith("cut:"):
                y1, y2 = map(float, r["verdict"][4:].split(","))
                pre[r["id"]] = [[[0.05, y1], [0.95, y1]], [[0.05, y2], [0.95, y2]]]
    auto = {}
    if "--predicted" in sys.argv:     # 机器预测折线 jsonl {"id","pre"}：预填，并出「采纳」按钮；人改或采纳后才算数
        for line in Path(sys.argv[sys.argv.index("--predicted") + 1]).read_text(encoding="utf-8").splitlines():
            r = json.loads(line); pre[r["id"]] = r["pre"]; auto[r["id"]] = True
    done = {}
    if "--done" in sys.argv:          # 人已标的折线（harvest 出来的 jsonl）→ 种进页面的已有裁决
        for line in Path(sys.argv[sys.argv.index("--done") + 1]).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if str(r.get("verdict", "")).startswith("poly:"):
                done[r["id"]] = {"v": r["verdict"], "t": r.get("t", 0)}
    rows, imgs = [], {}
    for i in ids:
        lb = labels[i]; fn = i.replace(":", "_") + ".png"
        imgs[i] = "data:image/png;base64," + base64.b64encode((d / "crops" / fn).read_bytes()).decode()
        rows.append({"id": i, "img": i, "title": f"{i}", **({"pre": pre[i]} if i in pre else {}), **({"auto": True} if i in auto else {}),
                     "note": f"你之前标的读法：上 {lb['top']}　中 {lb['mid']}　下 {lb['bot']}" + ("　｜　折线是机器按你已标的那批预测的" if i in auto else "")})
    html = render(TITLE, KEY, verdicts=done, css=CSS, page_js=PAGE_JS, payload={"rows": rows, "imgs": imgs})
    out.write_text(html, encoding="utf-8")
    print(f"{out}  {len(html)/1024:.0f} KB  {len(rows)} 卡")


if __name__ == "__main__":
    main()
