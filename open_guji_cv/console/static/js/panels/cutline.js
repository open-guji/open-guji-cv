// ── 拖切线（粘连格线理想切点金标）───────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。
// ⚠️ 本文件的事件绑定（原 clBind）在切分前**physically** 长在「夹注段卡」那一段里
// （方案 §三：改切线的事件绑定要去夹注段里找），是搬家时归位、不是重写。
// 用户 2026-09-05：「先让我添加一些金标，确定理想位置，再想算法。」
// 每张卡：上下两格的列图裁片（1:1 像素，CSS 放大 CL.scale 倍）+ 可拖横线。
// 每次落定立刻 POST 一条 cutline 事件（刷新不丢），verdict 见 touching-cuts README。
import { $, api } from '../api.js';
import { state } from '../state.js';

export const id = 'cutline';

const CL = { cases: [], cur: 0, y: {}, done: {}, scale: 2, seen: {}, tags: {}, scales: {}, poly: {}, mode: {}, pick: {} };

// 每张卡自己的显示倍率：列图裁片原宽约 180–210px，放到 ≤ 300px 且 ≤ 2 倍，
// 卡片再窄也不会把右侧按钮挤没（用户 2026-09-05 截图：图超出卡片、按钮挤成一列）。
function clScale(c) {
  const w = (c.col_w || (c.x1 - c.x0 + 12));
  const s = Math.min(2, Math.max(1, Math.floor(100 * 300 / w) / 100));
  CL.scales[c.id] = s;
  return s;
}

function clToggleTag(i, t) {
  const c = CL.cases[i];
  if (!c) return;
  CL.tags[c.id] = CL.tags[c.id] || {};
  CL.tags[c.id][t] = !CL.tags[c.id][t];
  const el = document.getElementById('clc' + i);
  if (el) el.querySelectorAll('.cltags button').forEach(b => b.classList.toggle('on', !!CL.tags[c.id][b.dataset.t]));
}

function clBatch() {   // 批次名带类型后缀：两类切线的金标别混在一批里
  const book = $('#cl_book').value || $('#book').value;
  const k = ($('#cl_kind') && $('#cl_kind').value) || 'r2s';
  const suffix = k === 'r2s' ? '' : '-' + k;
  return $('#cl_batch').value.trim() || `${book}-cutline${suffix}`;
}

// 算法给的候选有几种切法？≤1 就不显示「切法」那一行（多数格线只有直线一种）。
function clCands(c) { return c.candidates || []; }

function clCard(c, i) {
  const y = CL.y[c.id] ?? c.y;
  const d = CL.done[c.id] || '';
  const h = (c.crop_y1 - c.crop_y0), s = clScale(c);
  const cands = clCands(c);
  const pick = CL.pick[c.id] ?? c.chosen;
  const pickRow = cands.length > 1 ? `<div class="clbtns clcandbtns" title="算法给的切法候选（只读，看清了再选一种落定）">
      ${cands.map((cd, k) => `<button data-i="${i}" data-c="${k}" class="${k === pick ? 'on' : ''}"
        title="墨 ${cd.seam_ink} · 离直线 ${cd.dev_max}px">${CL_KIND[cd.kind] || cd.kind}</button>`).join('')}
      <span class="muted">墨/偏移：${cands.map(cd => `${cd.seam_ink}/${cd.dev_max}`).join(' · ')}</span>
    </div>` : '';
  return `<div class="clcard" id="clc${i}" data-i="${i}" data-done="${d}">
    <div class="clhead"><b>${c.id}</b><span class="muted">p${c.page} 列${c.col} 格线${c.bi} · 墨 ${c.ink}</span></div>
    <div class="clbody">
      <div class="climg" data-i="${i}" style="height:${h * s}px">
        <img src="${c.img}" height="${h * s}" alt="${c.id}" loading="lazy" style="width:auto;height:${h * s}px">
        <div class="clline old" style="top:${(c.y - c.crop_y0) * s}px"></div>
        <div class="clline" id="clln${i}" style="top:${(y - c.crop_y0) * s}px"></div>
        <svg class="clsvg" id="clsvg${i}" style="height:${h * s}px">${clSeamPath(c, s)}${clCandPaths(c, s)}<polyline id="clpl${i}" class="clpoly" points=""></polyline></svg>
      </div>
      <div class="clside">
        <div><span class="ch" title="上格期望字">${c.char_above || '？'}</span><span class="muted">上格 ${c.slot_above}</span></div>
        <div><span class="ch" title="下格期望字">${c.char_below || '？'}</span><span class="muted">下格 ${c.slot_below}</span></div>
        <div class="dy" id="cldy${i}">Δ ${y - c.y}px</div>
        ${pickRow}
        <div class="clbtns">
          <button data-i="${i}" data-v="moved" title="回车">落定</button>
          <button data-i="${i}" data-v="ok" title="O">现切点正确</button>
          <button data-i="${i}" data-v="seam_ok" title="G：绿色虚线（现役折线缝）已经是理想切法，直接记为折线金标"${c.seam ? '' : ' disabled'}>缝正确</button>
          <button data-i="${i}" data-v="cand" title="C：按上面选中的那条算法候选线落定，直接记为折线金标"${pick > 0 && cands[pick] && cands[pick].y ? '' : ' disabled'}>切法正确</button>
          <button data-i="${i}" data-v="overlap" title="V">重叠·折中</button>
          <button data-i="${i}" data-v="idk" title="S">拿不准</button>
          <button data-i="${i}" data-m="poly" class="clmode" title="P：折线模式。点空白处加点，点中已有点可拖动，右键删点">折线</button>
          <button data-i="${i}" data-m="clear" title="X：清空折线">清空</button>
          <button data-i="${i}" data-m="reopen" title="U：重开这张卡，改完再落定（后到覆盖）">重做</button>
          <span class="muted" id="clpn${i}"></span>
        </div>
        <div class="clbtns cltags" title="干扰因素（可多选，落定前点；评测里分开算）">
          <button data-i="${i}" data-t="stain" title="1">污点</button>
          <button data-i="${i}" data-t="border" title="2">界行/版框</button>
          <button data-i="${i}" data-t="residue" title="3">邻字残墨</button>
          <button data-i="${i}" data-t="other" title="4">其他</button>
        </div>
      </div>
    </div>
  </div>`;
}

const CL_KIND = { straight: '直线', seam_narrow: '窄走廊', seam_wide: '宽走廊' };

// 现役折线缝（case.seam：从内容窗口 x0 起、每 x 一个 y，列图坐标）画成虚线
function clSeamPath(c, s) {
  if (!c.seam || !c.seam.length) return '';
  const pts = c.seam.map((yy, k) => `${(c.x0 + k) * s},${(yy - c.crop_y0) * s}`).join(' ');
  return `<polyline class="clseam" points="${pts}"></polyline>`;
}

// 算法候选线（只读展示）。直线候选就是那条紫虚线（clline.old / clseam），不重复画。
function clCandPaths(c, s) {
  return clCands(c).map(cd => {
    if (!cd.y || !cd.y.length) return '';
    const cls = cd.kind === 'seam_wide' ? 'wide' : 'narrow';
    const pts = cd.y.map((yy, k) => `${(c.x0 + k) * s},${(yy - c.crop_y0) * s}`).join(' ');
    return `<polyline class="clcand ${cls}" points="${pts}"></polyline>`;
  }).join('');
}

// 点候选数：记下人工选了第几种切法（画面上把该按钮点亮）
function clPick(i, k) {
  const c = CL.cases[i]; if (!c) return;
  CL.pick[c.id] = k;
  const el = document.getElementById('clc' + i);
  if (el) el.querySelectorAll('.clcandbtns button').forEach(b => b.classList.toggle('on', +b.dataset.c === k));
  const btn = el && el.querySelector('button[data-v="cand"]');
  if (btn) btn.disabled = !(k > 0 && clCands(c)[k] && clCands(c)[k].y);
  $('#cl_msg').textContent = k === 0 ? '选的是「直线」——落定请用「落定 / 现切点正确」'
                                     : `选了「${CL_KIND[clCands(c)[k].kind] || ''}」，按 C 或点「切法正确」落定`;
}

function clRedrawPoly(i) {
  const c = CL.cases[i]; if (!c) return;
  const s = CL.scales[c.id] || CL.scale;
  const pts = (CL.poly[c.id] || []).slice().sort((a, b) => a[0] - b[0]);
  const pl = document.getElementById('clpl' + i);
  if (pl) pl.setAttribute('points', pts.map(([x, yy]) => `${x * s},${(yy - c.crop_y0) * s}`).join(' '));
  const svg = document.getElementById('clsvg' + i);
  if (svg) {
    svg.querySelectorAll('.clpt').forEach(e => e.remove());
    pts.forEach(([x, yy]) => {
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('class', 'clpt'); dot.setAttribute('r', '5');
      dot.setAttribute('cx', x * s); dot.setAttribute('cy', (yy - c.crop_y0) * s);
      svg.appendChild(dot);
    });
  }
  const n = document.getElementById('clpn' + i);
  if (n) n.textContent = CL.mode[c.id] === 'poly' ? `折线 ${pts.length} 点` : '';
  const el = document.getElementById('clc' + i);
  if (el) el.querySelectorAll('.clmode').forEach(b => b.classList.toggle('on', CL.mode[c.id] === 'poly'));
}

function clToggleMode(i) {
  const c = CL.cases[i]; if (!c) return;
  CL.mode[c.id] = CL.mode[c.id] === 'poly' ? 'line' : 'poly';
  clRedrawPoly(i);
}

function clAddPoint(i, x, y) {
  const c = CL.cases[i]; if (!c) return;
  x = Math.round(x); y = Math.max(c.crop_y0 + 1, Math.min(c.crop_y1 - 1, Math.round(y)));
  (CL.poly[c.id] = CL.poly[c.id] || []).push([x, y]);
  clRedrawPoly(i);
}

// 离 (x, y)（列图坐标）最近的顶点下标；超过 hitR 像素（显示坐标）算没点中
function clNearestPoint(i, x, y, hitR = 9) {
  const c = CL.cases[i]; if (!c) return -1;
  const s = CL.scales[c.id] || CL.scale;
  let best = -1, bd = Infinity;
  (CL.poly[c.id] || []).forEach(([px, py], k) => {
    const d = Math.hypot((px - x) * s, (py - y) * s);
    if (d < bd) { bd = d; best = k; }
  });
  return bd <= hitR ? best : -1;
}

function clMovePoint(i, k, x, y) {
  const c = CL.cases[i]; if (!c || !CL.poly[c.id] || !CL.poly[c.id][k]) return;
  CL.poly[c.id][k] = [Math.round(x), Math.max(c.crop_y0 + 1, Math.min(c.crop_y1 - 1, Math.round(y)))];
  clRedrawPoly(i);
}

function clRemovePoint(i, k) {
  const c = CL.cases[i]; if (!c || !CL.poly[c.id]) return;
  CL.poly[c.id].splice(k, 1); clRedrawPoly(i);
}

function clClearPoly(i) {
  const c = CL.cases[i]; if (!c) return;
  CL.poly[c.id] = []; clRedrawPoly(i);
}

// 重做：把已落定的卡恢复成未裁（再次落定会写一条新事件，后到覆盖）
function clReopen(i) {
  const c = CL.cases[i]; if (!c) return;
  delete CL.done[c.id];
  const el = document.getElementById('clc' + i);
  if (el) { el.dataset.done = ''; el.style.display = ''; el.querySelectorAll('.clbtns button[data-v]').forEach(b => b.classList.remove('on')); }
  clFocus(i);
  $('#cl_msg').textContent = `${c.id} 已重开，改完再落定（后到覆盖）`;
}

function clPopPoint(i) {
  const c = CL.cases[i]; if (!c || !CL.poly[c.id] || !CL.poly[c.id].length) return;
  CL.poly[c.id].pop(); clRedrawPoly(i);
}

function clSetY(i, y) {
  const c = CL.cases[i];
  if (!c) return;
  y = Math.max(c.crop_y0 + 1, Math.min(c.crop_y1 - 1, Math.round(y)));
  CL.y[c.id] = y;
  const ln = document.getElementById('clln' + i);
  if (ln) ln.style.top = `${(y - c.crop_y0) * (CL.scales[c.id] || CL.scale)}px`;
  const dy = document.getElementById('cldy' + i);
  if (dy) dy.textContent = `Δ ${y - c.y}px`;
}

function clFocus(i) {
  if (!CL.cases.length) return;
  const dir = i >= CL.cur ? 1 : -1;
  let j = Math.max(0, Math.min(i, CL.cases.length - 1));
  while (j >= 0 && j < CL.cases.length) {
    const el = document.getElementById('clc' + j);
    if (!el || el.style.display !== 'none') break;
    j += dir;
  }
  if (j < 0 || j >= CL.cases.length) j = Math.max(0, Math.min(i, CL.cases.length - 1));
  CL.cur = j;
  document.querySelectorAll('.clcard.cur').forEach(e => e.classList.remove('cur'));
  const el = document.getElementById('clc' + CL.cur);
  if (el) { el.classList.add('cur'); el.scrollIntoView({ block: 'nearest' }); }
}

async function clDecide(i, verdict) {
  const c = CL.cases[i];
  if (!c) return;
  let y = CL.y[c.id] ?? c.y;
  if (verdict === 'moved' && y === c.y) verdict = 'ok';   // 回车但没动 = 现切点正确
  if (verdict === 'ok') y = c.y;
  CL.done[c.id] = verdict;
  const el = document.getElementById('clc' + i);
  if (el) {
    el.dataset.done = verdict;
    el.querySelectorAll('.clbtns button').forEach(b => b.classList.toggle('on', b.dataset.v === verdict));
    if ($('#cl_todo').checked) el.style.display = 'none';
  }
  const now = Date.now();
  const tags = Object.keys(CL.tags[c.id] || {}).filter(t => CL.tags[c.id][t]);
  let polyline, cand;
  if (verdict === 'seam_ok') {
    if (!c.seam || !c.seam.length) { $('#cl_msg').textContent = '这条格线没有现役折线缝（绿虚线），用直线口径落定'; return; }
    // 把现役缝抽样成折线（每 6px 一个点 + 末点），记为人认可的折线金标
    const step = 6; polyline = [];
    for (let k = 0; k < c.seam.length; k += step) polyline.push([c.x0 + k, c.seam[k]]);
    if ((c.seam.length - 1) % step) polyline.push([c.x0 + c.seam.length - 1, c.seam[c.seam.length - 1]]);
    y = Math.round(c.seam.reduce((a, q) => a + q, 0) / c.seam.length);
  } else if (verdict === 'cand') {
    // 人认可的是**算法候选里的某一条**——记下是哪一种（下游打分函数要的正是这个：
    // 哪种切法被人选中了）。直线候选没有 y，走「落定」口径，不该按 C。
    const k = CL.pick[c.id] ?? c.chosen;
    const cd = clCands(c)[k];
    if (!cd || !cd.y || !cd.y.length) { $('#cl_msg').textContent = '选中的是「直线」，用「落定 / 现切点正确」'; return; }
    cand = cd.kind;
    const step = 6; polyline = [];
    for (let j = 0; j < cd.y.length; j += step) polyline.push([c.x0 + j, cd.y[j]]);
    if ((cd.y.length - 1) % step) polyline.push([c.x0 + cd.y.length - 1, cd.y[cd.y.length - 1]]);
    y = Math.round(cd.y.reduce((a, q) => a + q, 0) / cd.y.length);
  } else if (CL.mode[c.id] === 'poly') {
    const pts = (CL.poly[c.id] || []).slice().sort((a, b) => a[0] - b[0]);
    if (pts.length < 2) { $('#cl_msg').textContent = '折线模式至少要点 2 个点（Backspace 撤点，P 切回直线）'; return; }
    polyline = pts;
    y = Math.round(pts.reduce((a, q) => a + q[1], 0) / pts.length);   // 直线口径仍有个 y 可用
    if (verdict === 'ok') verdict = 'moved';
  }
  const row = { id: c.id, y, y_old: c.y, verdict, bi: c.bi, slot_above: c.slot_above, slot_below: c.slot_below,
                col_h: c.col_h, char_above: c.char_above || '', char_below: c.char_below || '',
                tags: tags.length ? tags : undefined, polyline, cand,
                client_ts: now, dwell_ms: CL.seen[c.id] ? now - CL.seen[c.id] : undefined };
  try {
    await api('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch: clBatch(), step: 'row_segment', unit: 'boundary', kind: 'cutline', events: [row] }) });
    const n = Object.keys(CL.done).length;
    $('#cl_msg').textContent = `已落 ${n} / ${CL.cases.length} 条 → 批次 ${clBatch()}`;
  } catch (e) {
    $('#cl_msg').textContent = '写入失败：' + e.message;
    delete CL.done[c.id];
    if (el) { el.dataset.done = ''; el.style.display = ''; }
    return;
  }
  clFocus(i + 1);
}

async function clLoad() {
  const book = $('#cl_book').value || $('#book').value;
  const pages = $('#cl_pages').value.trim() || 'body';
  const limit = +$('#cl_limit').value || 250;
  const batch = clBatch();
  $('#cl_msg').textContent = '载入中…（首次要做整理本对齐，约一分钟）';
  let d;
  try {
    d = await api(`/api/cutline/cases?book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
                  + `&limit=${limit}&batch=${encodeURIComponent(batch)}&skip_done=${$('#cl_todo').checked}`
                  + `&kind=${encodeURIComponent($('#cl_kind').value)}`);
  } catch (e) { $('#cl_msg').textContent = '失败：' + e.message; return; }
  let done = {};
  try { done = (await api(`/api/cutline/verdicts?batch=${encodeURIComponent(batch)}`)).verdicts || {}; } catch (e) { /* 新批次 */ }
  CL.cases = d.cases; CL.cur = 0; CL.y = {}; CL.done = {}; CL.seen = {}; CL.pick = {};
  const t0 = Date.now();
  d.cases.forEach(c => {
    CL.seen[c.id] = t0;
    if (done[c.id]) {
      CL.done[c.id] = done[c.id].verdict; if (done[c.id].y != null) CL.y[c.id] = done[c.id].y;
      if (done[c.id].polyline) { CL.poly[c.id] = done[c.id].polyline; CL.mode[c.id] = 'poly'; }
      // 上次按「切法正确」落定的，把选中的那条恢复成选中态（不恢复的话重开后
      // 手一点候选就跳回算法默认那条，人会以为自己的裁决没记住）
      if (done[c.id].cand) {
        const k = (c.candidates || []).findIndex(x => x.kind === done[c.id].cand);
        if (k >= 0) CL.pick[c.id] = k;
      }
    }
  });
  $('#cl_cards').innerHTML = d.cases.map(clCard).join('');
  d.cases.forEach((c, i) => { if (CL.poly[c.id]) clRedrawPoly(i); });
  if ($('#cl_todo').checked) d.cases.forEach((c, i) => { if (CL.done[c.id]) document.getElementById('clc' + i).style.display = 'none'; });
  const kindName = {r2s: '粘连 R2s', split_char: '切进字里', all: '粘连+切进字里'}[$('#cl_kind').value] || 'R2s';
  $('#cl_msg').textContent = `本册${kindName}共 ${d.n_r2s} 条，已有金标/已裁 ${d.n_done}，本次载入 ${d.n} 条 → 批次 ${batch}`;
  clFocus(0);
}

export function mount(root) {
  $('#cl_book').innerHTML = state.books.map(b => `<option value="${b.id}">${b.id}</option>`).join('');
  $('#cl_load').onclick = clLoad;
  const grid = $('#cl_cards');
  // 点击 / 拖动定位（坐标 → 列图像素）
  let dragging = null;
  const posY = (box, ev) => {
    const c = box.dataset && CL.cases[+box.dataset.i];
    return c ? c.crop_y0 + (ev.clientY - box.getBoundingClientRect().top) / (CL.scales[c.id] || CL.scale) : null;
  };
  const posX = (box, ev) => {
    const c = box.dataset && CL.cases[+box.dataset.i];
    return c ? (ev.clientX - box.getBoundingClientRect().left) / (CL.scales[c.id] || CL.scale) : null;
  };
  let dragPt = null;   // {box, i, k}：正在拖的折线顶点
  grid.addEventListener('mousedown', ev => {
    const box = ev.target.closest('.climg');
    if (!box) return;
    const i = +box.dataset.i; clFocus(i);
    const c = CL.cases[i];
    if (c && CL.mode[c.id] === 'poly') {
      const x = posX(box, ev), y = posY(box, ev);
      if (ev.button === 2) { const k = clNearestPoint(i, x, y); if (k >= 0) clRemovePoint(i, k); ev.preventDefault(); return; }
      const k = clNearestPoint(i, x, y);
      if (k >= 0) { dragPt = { box, i, k }; }
      else { clAddPoint(i, x, y); dragPt = { box, i, k: CL.poly[c.id].length - 1 }; }
      ev.preventDefault(); return;
    }
    dragging = box;
    clSetY(i, posY(box, ev)); ev.preventDefault();
  });
  grid.addEventListener('contextmenu', ev => { if (ev.target.closest('.climg')) ev.preventDefault(); });
  window.addEventListener('mousemove', ev => {
    if (dragPt) { clMovePoint(dragPt.i, dragPt.k, posX(dragPt.box, ev), posY(dragPt.box, ev)); return; }
    if (dragging) clSetY(+dragging.dataset.i, posY(dragging, ev));
  });
  window.addEventListener('mouseup', () => { dragging = null; dragPt = null; });
  grid.addEventListener('click', ev => {
    const b = ev.target.closest('.clbtns button');
    if (b && b.dataset.c != null) { clPick(+b.dataset.i, +b.dataset.c); clFocus(+b.dataset.i); return; }
    if (b && b.dataset.m === 'poly') { clToggleMode(+b.dataset.i); clFocus(+b.dataset.i); return; }
    if (b && b.dataset.m === 'clear') { clClearPoly(+b.dataset.i); clFocus(+b.dataset.i); return; }
    if (b && b.dataset.m === 'reopen') { clReopen(+b.dataset.i); return; }
    if (b && b.dataset.t) { clToggleTag(+b.dataset.i, b.dataset.t); clFocus(+b.dataset.i); return; }
    if (b) clDecide(+b.dataset.i, b.dataset.v);
    const card = ev.target.closest('.clcard');
    if (card && !b) clFocus(+card.dataset.i);
  });
  document.addEventListener('keydown', ev => {
    if (!$('#view-cutline').classList.contains('active')) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;   // 组合键（Ctrl+C 复制等）放行
    const c = CL.cases[CL.cur];
    if (!c) return;
    const step = ev.shiftKey ? 5 : 1;
    if (ev.key === 'ArrowUp') { clSetY(CL.cur, (CL.y[c.id] ?? c.y) - step); ev.preventDefault(); }
    else if (ev.key === 'ArrowDown') { clSetY(CL.cur, (CL.y[c.id] ?? c.y) + step); ev.preventDefault(); }
    else if (ev.key === 'Enter') { clDecide(CL.cur, 'moved'); ev.preventDefault(); }
    else if (ev.key === 'o' || ev.key === 'O') { clDecide(CL.cur, 'ok'); ev.preventDefault(); }
    else if (ev.key === 'g' || ev.key === 'G') { clDecide(CL.cur, 'seam_ok'); ev.preventDefault(); }
    else if (ev.key === 'c' || ev.key === 'C') { clDecide(CL.cur, 'cand'); ev.preventDefault(); }
    else if (ev.key === 'v' || ev.key === 'V') { clDecide(CL.cur, 'overlap'); ev.preventDefault(); }
    else if (ev.key === 's' || ev.key === 'S') { clDecide(CL.cur, 'idk'); ev.preventDefault(); }
    else if (ev.key === 'ArrowRight' || ev.key === 'j') { clFocus(CL.cur + 1); ev.preventDefault(); }
    else if (ev.key === 'ArrowLeft' || ev.key === 'k') { clFocus(CL.cur - 1); ev.preventDefault(); }
    else if (['1', '2', '3', '4'].includes(ev.key)) {
      clToggleTag(CL.cur, ['stain', 'border', 'residue', 'other'][+ev.key - 1]); ev.preventDefault();
    }
    else if (ev.key === 'p' || ev.key === 'P') { clToggleMode(CL.cur); ev.preventDefault(); }
    else if (ev.key === 'Backspace') { clPopPoint(CL.cur); ev.preventDefault(); }
    else if (ev.key === 'x' || ev.key === 'X') { clClearPoly(CL.cur); ev.preventDefault(); }
    else if (ev.key === 'u' || ev.key === 'U') { clReopen(CL.cur); ev.preventDefault(); }
  });
}

export const refresh = clLoad;
