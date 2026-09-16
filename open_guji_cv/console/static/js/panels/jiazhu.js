// ── 夹注段卡 ───────────────────────────────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。
// 数据来自 /api/jiazhu/segments（seed_admit + row_segment + 整理本对齐）。
// **段是审阅单位**：一段版本注 5–19 字，人一眼读完整句就知道通不通；
// 逐格出卡等于把一句话拆成十几道题，既慢又看不出段本身对不对。
// 裁决复用现成协议：整段确认/改格 → confirm 事件；切分缺陷 → seg_defect。
import { $, api } from '../api.js';
import { needsReading, consumedMsg } from '../shared/domain.js';
import { state } from '../state.js';

export const id = 'jiazhu';

const JZ = { segs: [], edit: {}, defect: {} };

function jzBatch() {
  return $('#jz_batch').value.trim() || ($('#jz_book').value + '-jiazhu');
}

export async function jzLoad() {
  const book = $('#jz_book').value || $('#book').value;
  const pages = $('#jz_pages').value || 'jz';
  const only = $('#jz_only').value;
  $('#jz_msg').textContent = '载入中…';
  let d;
  try {
    d = await api(`/api/jiazhu/segments?book=${encodeURIComponent(book)}`
      + `&pages=${encodeURIComponent(pages)}&only=${only}`
      + `&batch=${encodeURIComponent(jzBatch())}`);
  } catch (e) { $('#jz_msg').textContent = e.message; return; }
  JZ.segs = d.segments; JZ.edit = {}; JZ.defect = {};
  jzRender();
  $('#jz_msg').textContent = `${d.pages.length} 页，段 ${d.n}（含待审 ${d.n_review}）→ 批次 ${jzBatch()}`;
}

function jzRender() {
  if (!JZ.segs.length) { $('#jz_cards').innerHTML = '<div class="muted">没有夹注段</div>'; return; }
  $('#jz_cards').innerHTML = JZ.segs.map((s, i) => {
    const cells = s.cells.map((c, j) => {
      const ed = JZ.edit[c.id];
      const shown = ed !== undefined ? ed : (c.char || '□');
      const cls = ed !== undefined ? 'jzc-edit' : (c.admit ? 'jzc-auto' : 'jzc-rev');
      const suspectCls = c.suspect ? ' jzc-suspect' : '';
      const ref = c.ref && c.ref !== shown ? `<span class="jzref">${c.ref}</span>` : '';
      const title = c.suspect ? `${c.id} · ${c.channel || '待审'} · 疑似整宽字被误劈` : `${c.id} · ${c.channel || '待审'}`;
      return `<span class="jzcell ${cls}${suspectCls}" data-i="${i}" data-j="${j}" title="${title}">`
        + `<img src="${c.patch}" alt="" loading="lazy"><b>${shown}</b>${ref}</span>`;
    }).join('');
    const same = s.ref && s.ref.replace(/·/g, '') === s.text.replace(/□/g, '');
    const badge = s.n_review
      ? `<span class="badge b-pending">待审 ${s.n_review}</span>`
      : '<span class="badge b-completed">全自动</span>';
    // 疑似型 1（夹注被当正文）：jiazhu_split.suspect_full_width_cells 标出的
    // 段，几何判据只是提示，最终要不要认定为「夹注被当正文」由人在这里裁决
    // （见 review-feedback：2026-09-10 全书核实，几何判据不能自动裁剪）。
    const suspectBadge = s.n_suspect
      ? `<span class="badge b-warn">疑似整宽字被误劈 ${s.n_suspect}</span>` : '';
    const dfl = JZ.defect[s.id];
    return `<div class="jzcard${s.n_suspect ? ' jzcard-suspect' : ''}" id="jzs${i}">
      <div class="jzhead">
        <span class="mono">${s.id}</span> ${badge} ${suspectBadge}
        <span class="muted">${s.n} 格 · a ${s.a.length} / b ${s.b.length}</span>
        ${same ? '<span class="badge b-completed">与整理本一致</span>' : '<span class="badge b-pending">与整理本有出入</span>'}
      </div>
      <div class="jzbody">
        <img class="jzstrip" src="${s.img}" alt="列条" loading="lazy">
        <div class="jztext">
          <div class="jzline"><span class="jzlab">转写</span>${cells}</div>
          <div class="jzline"><span class="jzlab">整理本</span><span class="mono jzrefline">${s.ref || '—'}</span></div>
          <div class="jzacts">
            <button data-act="ok" data-i="${i}">整段确认</button>
            <button data-act="defect" data-i="${i}" class="${dfl ? 'on' : ''}">标切分缺陷${dfl ? `（${dfl.note}）` : ''}</button>
            <span class="muted jzhint">点某一格可改字</span>
          </div>
        </div>
      </div>
    </div>`;
  }).join('');
}

function jzBind(root) {
  $('#jz_book').innerHTML = state.books.map(b => `<option value="${b.id}">${b.id}</option>`).join('');
  if (state.books.some(b => b.id === 'vol02')) $('#jz_book').value = 'vol02';
  $('#jz_load').onclick = jzLoad;
  $('#jz_submit').onclick = jzSubmit;
  $('#jz_cards').onclick = (ev) => {
    const cell = ev.target.closest('.jzcell');
    if (cell) {
      const s = JZ.segs[+cell.dataset.i], c = s.cells[+cell.dataset.j];
      const cur = JZ.edit[c.id] !== undefined ? JZ.edit[c.id] : (c.char || '');
      const v = prompt(`${c.id}
整理本：${c.ref || '—'}
改成（留空=撤销改动）：`, cur);
      if (v === null) return;
      if (v.trim()) JZ.edit[c.id] = v.trim(); else delete JZ.edit[c.id];
      jzRender();
      return;
    }
    const btn = ev.target.closest('button[data-act]');
    if (!btn) return;
    const s = JZ.segs[+btn.dataset.i];
    if (btn.dataset.act === 'ok') {
      // 整段确认 = 这一段每一格都按当前显示的字落 confirm
      s.cells.forEach(c => { if (JZ.edit[c.id] === undefined) JZ.edit[c.id] = c.char || ''; });
      jzRender();
      $('#jz_msg').textContent = `已标记整段 ${s.id}（${s.n} 格），记得点「提交裁决」`;
    } else {
      // 结构化缺陷类型：quality 沿用四分类（truncated/contaminated），
      // defect 是细分子类——夹注被当正文 / 夹注被截断是本轮新加的两类，
      // 之前全靠自由文本 note 事后人工阅读才能发现（见
      // .claude/doc/jiazhu_defects_for_segmentation.md 型1/型2）。
      const options = [
        { key: 'jiazhu_as_body', label: '夹注被当正文（整宽正文字被劈成a/b两半）', quality: 'contaminated' },
        { key: 'jiazhu_truncated', label: '夹注被截断（子列右/左缘裁进笔画）', quality: 'truncated' },
        { key: 'jiazhu_too_few', label: '少格（漏拆，字数比实际注文少）', quality: 'truncated' },
        { key: 'jiazhu_too_many', label: '多格（多切，字数比实际注文多）', quality: 'contaminated' },
        { key: 'jiazhu_ab_swapped', label: 'ab分错边', quality: 'contaminated' },
        { key: 'other', label: '其他', quality: 'contaminated' },
      ];
      // 机器已标疑似型 1（跨缝连通体面积占比高）时，把默认序号指向对应选项，
      // 减少一次多余的挑选——最终仍由人确认，机器判据不自动生效。
      const cur = JZ.defect[s.id]?.key || (s.n_suspect ? 'jiazhu_as_body' : 'jiazhu_too_few');
      const menu = options.map((o, i) => `${i + 1}. ${o.label}`).join('\n');
      const pick = prompt(`切分缺陷类型（输入序号）：\n${menu}`,
                           String(options.findIndex(o => o.key === cur) + 1 || 1));
      if (pick === null) return;
      const idx = parseInt(pick.trim(), 10) - 1;
      const opt = options[idx];
      if (!opt) { $('#jz_msg').textContent = '序号无效，未记录'; return; }
      let note = opt.label;
      if (opt.key === 'other') {
        const free = prompt('具体说明：', '');
        if (free && free.trim()) note = free.trim();
      }
      JZ.defect[s.id] = { key: opt.key, quality: opt.quality, note };
      jzRender();
    }
  };
}

async function jzSubmit() {
  const batch = jzBatch();
  const rows = [];
  for (const s of JZ.segs) {
    for (const c of s.cells) {
      const v = JZ.edit[c.id];
      if (v === undefined || !v) continue;
      // shape = 刻本形（人看图定的），reading 只有 己已巳 才分（与审查页同口径）
      rows.push({ id: c.id, v: 'confirm', shape: v,
                  reading: needsReading(v) ? (c.ref || v) : v,
                  conversion: 0, client_ts: Date.now() / 1000 });
    }
  }
  // 段级切分缺陷：落在**段首格**上（金标信封按字位锚定，没有段级锚点），
  // 与审查页同一条协议——`kind` 仍是 confirm，`v: 'seg_defect'` 才是载荷判别，
  // quality 沿用 char-segmentation/instances 的四分类（不另造词）；
  // defect 是新加的结构化子类（jiazhu_as_body / jiazhu_truncated / …），
  // 之前这一层全靠自由文本 note，无法批量检索统计（2026-09-10 改）。
  const defects = [];
  for (const s of JZ.segs) {
    const why = JZ.defect[s.id];
    if (!why) continue;
    defects.push({ id: s.cells[0].id, v: 'seg_defect', quality: why.quality, defect: why.key,
                   shape: s.cells[0].char || '', reading: s.cells[0].char || '',
                   note: `jiazhu_split ${s.id} ${s.n}格 ${why.note}`,
                   client_ts: Date.now() / 1000 });
  }
  if (!rows.length && !defects.length) { $('#jz_msg').textContent = '还没有裁决'; return; }
  $('#jz_msg').textContent = '提交中…';
  let n = 0, msg = '';
  try {
  if (rows.length) {
    const r = await api('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows }) });
    n += r.appended ?? rows.length; msg += consumedMsg(r);
  }
  if (defects.length) {
    const r2 = await api('/api/events', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: defects }) });
    n += r2.appended ?? defects.length;
  }
  } catch (e) {
    // 别停在「提交中…」——提交失败必须说出来（第一次冒烟就栽在这：
    // seg_defect 不是合法 kind，前端却一直显示「提交中…」）
    $('#jz_msg').textContent = '提交失败：' + e.message;
    return;
  }
  $('#jz_msg').textContent = `已写入 ${n} 条事件 → 批次 ${batch}` + msg;
  JZ.edit = {}; JZ.defect = {};
  jzLoad();
}

export function mount(root) {
  jzBind(root);
}

export function refresh() {
  if (!JZ.segs.length) jzLoad();
}
