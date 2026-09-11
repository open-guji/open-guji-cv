// ── 组视图：列 = 形，格 = 图块 ────────────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。
// 数据来自 /api/variants/groups；裁决复用 /api/events 的 confirm 协议（shape/reading/conversion），
// 与单卡裁决落到同一条路由 → glyphdb_admit → 账本下次重建就记住。
import { $, api } from '../api.js';
import { needsReading, consumedMsg } from '../shared/domain.js';

export const id = 'groups';

let VG = { data: null, cur: null, state: {}, sel: null };

export async function vgLoad() {
  const book = $('#book').value, pages = $('#vg_pages').value.trim() || 'dev_set';
  $('#vg_stat').textContent = '读取中…';
  try {
    VG.data = await api(`/api/variants/groups?book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`);
  } catch (e) { $('#vg_stat').textContent = e.message; return; }
  VG.cur = null; VG.state = {}; VG.sel = null;
  const gs = VG.data.groups || [];
  const nStale = gs.reduce((a, g) => a + (g.n_stale || 0), 0);
  $('#vg_stat').textContent = `${gs.length} 组 · 待审 ${gs.reduce((a, g) => a + g.n_pending, 0)} 格 · 已自动放行 ${gs.reduce((a, g) => a + g.n_tiles - g.n_pending, 0)} 格`
    + (nStale ? ` · 已裁待重跑 ${nStale} 格` : '');
  // 已裁但产物没跟上的页（重跑只跑这几页，不必全量）
  VG.stalePages = [...new Set(gs.flatMap(g => g.tiles.filter(t => t.stale).map(t => t.page)))].sort((a, b) => a - b);
  $('#vg_stale').innerHTML = nStale
    ? `⟳ 有 ${nStale} 格你已经裁过、但产物还是上次跑管线时的结果（<b style="color:#B8860B">黄框</b>）——`
      + `裁决没丢，已经在库里，只是这张视图读的是产物。`
      + `<button id="vg_resync" style="margin-left:.4rem">重跑这 ${VG.stalePages.length} 页同步</button>`
      + `<span class="mono" style="margin-left:.4rem">p${VG.stalePages.join(' p')}</span>`
    : '';
  const rs = $('#vg_resync');
  if (rs) rs.onclick = () => vgResync();
  // 有异体故事的组在前：有待审格，或这些页里真刻了 ≥2 种形。其余（账本因一条字典边把 洧 挂到
  // 有 名下这类，这些页里只刻了一种形）折到后面——它们不是抽审的靶子。
  // 「有故事」= 有待审格，或真刻了 ≥2 种形，或有字形→文意的转换（髪 读作 髮）——转换正是保真抽审的靶子
  const story = g => g.n_pending > 0 || g.n_stale > 0 || g.n_audit > 0
                     || new Set(g.tiles.filter(t => t.char).map(t => t.char)).size >= 2
                     || g.tiles.some(t => t.reading && t.char && t.reading !== t.char);
  const btn = (g, k) => `<button class="vgbtn" data-k="${k}"><span class="vgl">${g.canonical}</span> ${g.members.filter(m => m !== g.canonical).join(' ')}
       <sub>${g.n_tiles}${g.n_pending ? ' · 待审 ' + g.n_pending : ''}${g.n_audit ? ' · 待抽审 ' + g.n_audit : ''}${g.n_stale ? ' · 待重跑 ' + g.n_stale : ''}</sub></button>`;
  const main = gs.map((g, k) => [g, k]).filter(([g]) => story(g)), rest = gs.map((g, k) => [g, k]).filter(([g]) => !story(g));
  $('#vg_groups').innerHTML = (main.map(([g, k]) => btn(g, k)).join('') || '<span class="muted">这些页里没有待审或多形的组</span>')
    + (rest.length ? `<details class="vgrest"><summary class="muted">其余 ${rest.length} 组（这些页里只刻了一种形）</summary>${rest.map(([g, k]) => btn(g, k)).join('')}</details>` : '');
  $('#vg_groups').querySelectorAll('.vgbtn').forEach(b => b.onclick = () => vgShow(+b.dataset.k));
  $('#vg_grid').innerHTML = ''; $('#vg_actions').style.display = 'none';
  if (main.length) vgShow(main[0][1]); else if (gs.length) vgShow(0);
}

// 重跑「已裁待重跑」那几页：从 glyph_match 起（库变了才要重算匹配），跑完自动刷新视图。
async function vgResync() {
  const pages = (VG.stalePages || []).join(',');
  if (!pages) return;
  const btn = $('#vg_resync');
  if (btn) { btn.disabled = true; btn.textContent = '重跑中…'; }
  try {
    const job = await api('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book: $('#book').value, pipeline: 'keben_body_v2',
                             from_step: 'glyph_match', pages, force: true }) });
    // 轮询到结束（这几页通常十几秒）。状态取值见 console/jobs.py：
    // pending / running / completed / failed / cancelled
    for (let i = 0; i < 240; i++) {
      await new Promise(r => setTimeout(r, 1000));
      const j = await api('/api/runs/' + job.id);
      if (btn) btn.textContent = `重跑中… ${j.duration ? j.duration + 's' : ''}`;
      if (['completed', 'failed', 'cancelled'].includes(j.status)) {
        if (j.status !== 'completed') {
          $('#vg_stale').textContent = `重跑 ${j.status}（exit ${j.exit_code}）：去「运行」页看日志`;
          return;
        }
        break;
      }
    }
    await vgLoad();
  } catch (e) {
    $('#vg_stale').textContent = '重跑失败：' + e.message;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '重跑同步'; }
  }
}

function vgShow(k) {
  const g = VG.data.groups[k]; VG.cur = k; VG.sel = null;
  $('#vg_groups').querySelectorAll('.vgbtn').forEach(b => b.classList.toggle('active', +b.dataset.k === k));
  // 每格当前所在列：待审的先放本书偏好形（preferred），已放行的放它存的形
  for (const t of g.tiles) {
    if (!VG.state[t.id]) VG.state[t.id] = { col: t.char || g.preferred || g.members[0], orig: t.char, mark: '', changed: false };
  }
  vgRender();
}

function vgRender() {
  const g = VG.data.groups[VG.cur];
  const cols = g.members.slice();
  const byCol = Object.fromEntries(cols.map(c => [c, []]));
  for (const t of g.tiles) { const s = VG.state[t.id]; if (s.other) continue; (byCol[s.col] || (byCol[s.col] = [])).push(t); }
  const fm = g.forms || {};
  // 组外列：正确答案根本不在这一组里的格（标 蠹 实际是 𥗤——那不是异体，是认错字）。
  // 组视图只在组内几个形之间转是不够的，这一列收容它们，字由人填。
  const others = g.tiles.filter(t => VG.state[t.id].other);
  $('#vg_grid').innerHTML = `<div class="vgrid" style="grid-template-columns:repeat(${cols.length},minmax(0,1fr))">`
    + cols.map(c => {
      const f = fm[c] || { book: {}, ref: 0 }; const b = f.book || {};
      const carved = (b.products || 0) + (b.db || 0) - (b.align || 0);
      return `<div class="vcol"><div class="vhead"><span class="vgl">${c}</span>
          <span class="muted">刻 ${Math.max(0, carved)}${b.human ? '·人' + b.human : ''} · 整理本 ${f.ref || 0}${c === g.reading_default ? ' · 文意' : ''}${c === g.preferred ? ' · 本书惯用' : ''}</span></div>
        <div class="vtiles">${(byCol[c] || []).map(t => {
          const s = VG.state[t.id];
          const cls = ['vtile', t.pending ? 'pending' : '', t.stale ? 'stale' : '', t.audit ? 'audit' : '', s.changed ? 'moved' : '', s.mark ? 'marked' : '', t.human ? 'hum' : '', VG.sel === t.id ? 'sel' : ''].filter(Boolean).join(' ');
          const tip = `${t.id} · ${t.pending ? '待审' : (t.stale ? '你已裁「' + t.human + '」，产物待重跑' : '自动 ' + (t.channel || ''))}${t.state ? ' · ' + t.state : ''}${t.human ? ' · 人裁 ' + t.human : ''}\n单击=选中　双击/空格/←→=换列　O 组外　N 非字　T 字形不完整　C 有噪声`;
          const badge = s.mark ? `<b>${{ non: 'N', truncated: 'T', contaminated: 'C' }[s.mark]}</b>` : (t.human ? `<i>${t.human}</i>` : '');
          // **不用 loading="lazy"**：组视图是「一眼扫完整组」的界面，抽审时图必须都在，
          // 懒加载会让视口外的格子空着（截图与快速滚动时尤其明显）。字块 3–4KB，
          // 一组几十个也就百来 KB，全加载没有负担。
          return `<div class="${cls}" data-id="${t.id}" title="${tip}" tabindex="0"><img src="${t.patch}" alt="${t.id}">${badge}</div>`;
        }).join('')}</div></div>`;
    }).join('') + '</div>'
    + `<div class="vother${others.length ? '' : ' empty'}">
        <div class="vhead"><span class="muted">组外（不是这一组的任何一个形；选中格子按 <b>O</b> 扔进来，再填它到底是什么字；填错了在框里按 <b>Esc</b> 放回）</span></div>
        <div class="vtiles">${others.map(t => {
          const s = VG.state[t.id];
          return `<div class="votile"><div class="vtile marked" data-id="${t.id}" title="${t.id}\n再按 O 放回组内" tabindex="0"><img src="${t.patch}" loading="lazy" alt="${t.id}"><b>O</b></div>
            <input class="voin" data-id="${t.id}" value="${s.otherChar || ''}" placeholder="是什么字" size="3" title="填图上实际刻的字；留空则提交时跳过这一格。按 Esc 放回组内"></div>`;
        }).join('')}</div></div>`;
  $('#vg_actions').style.display = '';
  const MARKS = { n: 'non', t: 'truncated', c: 'contaminated' };
  $('#vg_grid').querySelectorAll('.voin').forEach(inp => {
    inp.oninput = () => { const s = VG.state[inp.dataset.id]; s.otherChar = inp.value.trim(); s.changed = true; };
    // 退路：按 O 之后焦点在这个框里，再按 O 就是往框里打字了（本该如此——人要填字）。
    // Esc 把这一格放回组内，焦点还给格子。
    inp.onkeydown = ev => {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      const id = inp.dataset.id, s = VG.state[id];
      s.other = false; s.otherChar = ''; s.changed = s.col !== s.orig;
      VG.sel = id;
      vgRender();
    };
  });
  // 换列（点击 / 方向键 / 空格都走这里）
  const moveCol = (id, dir) => {
    const s = VG.state[id];
    if (s.other) return;
    const i = cols.indexOf(s.col);
    s.col = cols[(i + dir + cols.length) % cols.length];
    s.changed = s.col !== s.orig;
    s.mark = '';
    vgRender();
  };
  $('#vg_grid').querySelectorAll('.vtile').forEach(el => {
    // **点击只选中，不改形**（用户 2026-09-05 实锤：「点格子就动了，永远无法取得焦点」——
    // 此前点击既换列又是取焦点的唯一途径，vgRender 重绘还会把焦点冲掉，键盘那几个键
    // 等于废的）。换形改用双击 / ←→ / 空格，键盘标记则先点选再按。
    el.onclick = () => { VG.sel = el.dataset.id; el.focus(); };
    el.ondblclick = () => moveCol(el.dataset.id, +1);
    // N 非字 / T 字形不完整 / C 有噪声——后两个是「这块图切坏了」，与「这是什么字」
    // 是两件事：提交后走 seg_defect → 金标 + 排除名单，这一格以后不进库也不再出卡。
    el.onkeydown = ev => {
      const k = ev.key.toLowerCase();
      const id = el.dataset.id;
      const s = VG.state[id];
      VG.sel = id;
      if (ev.key === 'ArrowRight' || ev.key === ' ' || ev.key === 'Enter') { ev.preventDefault(); moveCol(id, +1); return; }
      if (ev.key === 'ArrowLeft') { ev.preventDefault(); moveCol(id, -1); return; }
      if (k === 'o') {           // 组外：正确答案不在这一组里
        ev.preventDefault();
        s.other = !s.other;
        s.mark = '';
        s.changed = s.other || s.col !== s.orig;
        vgRender();
        const box = $('#vg_grid').querySelector(`.voin[data-id="${CSS.escape(id)}"]`);
        if (box) box.focus();
        return;
      }
      const m = MARKS[k];
      if (!m) return;
      ev.preventDefault();
      s.mark = s.mark === m ? '' : m;
      s.changed = true;
      vgRender();
    };
  });
  // 重绘后把焦点还回选中的那一格——否则连按两个键第二下就落空了
  if (VG.sel) {
    const back = $('#vg_grid').querySelector(`.vtile[data-id="${CSS.escape(VG.sel)}"]`);
    if (back) back.focus({ preventScroll: true });
  }
}

async function vgSend(all) {
  const g = VG.data.groups[VG.cur]; if (!g) return;
  const book = $('#book').value, now = Date.now();
  const rows = [];
  let skipped = 0;
  for (const t of g.tiles) {
    const s = VG.state[t.id];
    if (!all && !t.pending && !s.changed) continue;
    if (s.mark === 'non') { rows.push({ id: t.id, v: 'not_a_char', client_ts: now }); continue; }
    // 切分缺陷：不是「这是什么字」的裁决，而是「这块图不能用」。quality 沿用
    // char-segmentation/instances 金标的四分类；顺手认出的字一并带上（人看图时
    // 认出来的不该丢）。下游 gold_add 落金标、crop_exclude 进排除名单。
    if (s.mark === 'truncated' || s.mark === 'contaminated') {
      const dshape = s.col;
      rows.push({ id: t.id, v: 'seg_defect', quality: s.mark,
                  shape: dshape, reading: needsReading(dshape) ? (g.reading_default || dshape) : dshape,
                  client_ts: now });
      continue;
    }
    // 组外：字形与文意都取人填的那个字（它跟这一组无关，整理本字不该当它的 reading）
    if (s.other) {
      if (!s.otherChar) { skipped++; continue; }
      rows.push({ id: t.id, v: 'confirm', shape: s.otherChar, reading: s.otherChar,
                  conversion: 0, client_ts: now, group: 'out:' + g.canonical });
      continue;
    }
    // 只有 己/已/巳 才分字形/文意（needsReading，见共享工具的说明）。组视图
    // 此前对**所有组**都无条件把 reading 填成 g.reading_default（整理本字），于是选
    // 𠮓（變的刻本异体）也被记成「文意=變」的一次转换——库/账本/字形层因此存对了刻本形，
    // 但 admissions.reading、判据 A 的转换计数都被污染。规则改成：shape 不在 己已巳 时
    // reading 必须等于 shape（不算转换）；shape 在 己已巳 时才取整理本字当文意兜底。
    const shape = s.col;
    const reading = needsReading(shape)
      ? (t.reading && t.reading !== t.char ? t.reading : (g.reading_default || shape))
      : shape;
    rows.push({ id: t.id, v: 'confirm', shape, reading: reading || shape,
                conversion: (reading && reading !== shape) ? 1 : 0, client_ts: now, group: g.canonical });
  }
  if (!rows.length) { $('#vg_msg').textContent = skipped ? `组外那 ${skipped} 格还没填字` : '没有要提交的格'; return; }
  const batch = `${book}-variants-${g.canonical}`;
  $('#vg_msg').textContent = `提交 ${rows.length} 条…`;
  try {
    const r = await api('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch, step: 'admit_decide', unit: 'cell', kind: 'confirm', events: rows }) });
    $('#vg_msg').textContent = `已写 ${r.appended} 条到批次 ${batch}`
      + (skipped ? `（组外 ${skipped} 格没填字，跳过）` : '')
      + consumedMsg(r);
    for (const row of rows) { const s = VG.state[row.id]; s.orig = s.col; s.changed = false; }
    for (const t of g.tiles) if (rows.some(r => r.id === t.id)) { t.pending = false; t.human = VG.state[t.id].col; }
    vgRender();
  } catch (e) { $('#vg_msg').textContent = e.message; }
}

export function mount(root) {
  const vl = $('#vg_load');
  if (vl) vl.onclick = vgLoad;
  const s1 = $('#vg_send_changed'), s2 = $('#vg_send_all');
  if (s1) s1.onclick = () => vgSend(false);
  if (s2) s2.onclick = () => vgSend(true);
}

export const refresh = vgLoad;
