// ── 异体：本书用字账（只读）──────────────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。
// 数据全部来自 /api/variants/book（config/variants/books/<套>.json），页面不算账。
import { $, api } from '../api.js';

export const id = 'variants';

let VAR = null;

export async function loadVariants() {
  const stat = $('#var_stat');
  stat.textContent = '读取中…';
  try {
    VAR = await api(`/api/variants/book?edition=${encodeURIComponent($('#var_edition').value.trim() || 'wuyingdian_zongmu')}`);
  } catch (e) { stat.textContent = e.message; $('#var_tbl').innerHTML = ''; $('#var_unknown').textContent = ''; VAR = null; return; }
  renderVariants();
}

function renderVariants() {
  if (!VAR) return;
  const m = VAR.meta || {}, s = m.stats || {}, inp = m.inputs || {};
  $('#var_stat').textContent = `${m.edition} · 组 ${s.groups}（整理本单形 ${s.ref_single} / 多形 ${s.ref_multi}）· 转换对 ${s.pairs} · 关系图外 ${s.unknown_pairs} · 产物 ${inp.products_records} 条 / glyph.db ${inp.glyph_db_instances} 例 · ${m.built_at || ''}`;
  const q = ($('#var_q').value || '').trim();
  // 刻本真刻的次数：products + db − align（align 是 v1 拿整理本贴的标签，不算刻本证据）
  const carved = (g, mm) => { const b = g.forms[mm].book; return b.products + b.db - b.align; };
  const weight = g => Object.values(g.pairs).reduce((a, p) => a + p.n, 0) * 10
                     + g.members.filter(mm => mm !== g.canonical).reduce((a, mm) => a + Math.max(0, carved(g, mm)), 0);
  const rows = Object.values(VAR.groups || {})
    .filter(g => !q || [...q].some(ch => g.members.includes(ch)))
    .sort((a, b) => weight(b) - weight(a) || a.canonical.localeCompare(b.canonical));
  const sub = (n, h) => `<sub>${n}${h ? '·人' + h : ''}</sub>`;
  $('#var_tbl').innerHTML = rows.length ? `<table class="jobs vtbl"><thead><tr>
      <th>组</th><th>刻本形</th><th>整理本形</th><th>转换对（刻本形→文意）</th><th>整理本</th><th>分型（先验）</th></tr></thead><tbody>`
    + rows.map(g => {
      const forms = g.members.map(mm => { const n = carved(g, mm); if (n <= 0) return '';
        return `<span class="${mm === g.preferred ? 'vpref' : ''}">${mm}${sub(n, g.forms[mm].book.human)}</span>`; }).filter(Boolean).join(' ');
      const refs = g.members.map(mm => g.forms[mm].ref > 0 ? `${mm}${sub(g.forms[mm].ref, 0)}` : '').filter(Boolean).join(' ');
      const pairs = Object.entries(g.pairs).map(([k, v]) => `${k}${sub(v.n, v.human)}`).join(' ');
      const tiers = g.members.filter(mm => mm !== g.canonical).map(mm => `${mm}:${g.forms[mm].tier || '—'}`).join(' ');
      return `<tr><td class="vgl">${g.canonical}</td><td>${forms || '—'}</td><td>${refs || '—'}</td><td>${pairs || '—'}</td><td>${g.ref_policy}</td><td class="muted">${tiers}</td></tr>`;
    }).join('') + '</tbody></table>' : '<span class="muted">没有匹配的组</span>';
  const un = VAR.unknown_pairs || [];
  $('#var_unknown').innerHTML = un.length
    ? '关系图里没有这条边、或两头落在不同组的转换对（新异体 / OCR 错 / 整理本错 三选一，待审）：'
      + un.map(u => `${u.shape}→${u.reading}<sub>${u.n}${u.human ? '·人' + u.human : ''}</sub>`).join('　')
    : '';
}

export function mount(root) {
  const r = $('#var_reload'), qi = $('#var_q');
  if (r) r.onclick = loadVariants;
  if (qi) qi.oninput = renderVariants;
}

export function refresh() {
  if (!VAR) loadVariants();
}
