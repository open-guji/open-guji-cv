// ── 总览 ───────────────────────────────────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。状态矩阵格子点击要跳到
// 「产物」面板——那是另一个面板，按约定不直接 import，由 mount() 的 deps 转接。
import { $, api, STATUS_MARK } from '../api.js';
import { state } from '../state.js';

export const id = 'overview';

let _openProduct = () => {};

export function mount(root, deps = {}) {
  if (deps.openProduct) _openProduct = deps.openProduct;
}

export async function refreshStatus() {
  const book = $('#book').value, pl = $('#pipeline').value, pages = $('#pages').value || 'dev_set';
  // 状态是相对某套参数的：用覆盖参数跑出的产物，在默认参数视角下永远显示过期。
  // 所以把「运行」里填的那套覆盖一并带上，跑完才能看到它变绿。
  const raw = ($('#params') && $('#params').value.trim()) || '';
  let qs = `book=${encodeURIComponent(book)}&pipeline=${encodeURIComponent(pl)}&pages=${encodeURIComponent(pages)}`;
  if (raw) qs += `&param_json=${encodeURIComponent(raw)}`;
  try {
    state.status = await api(`/api/status?${qs}`);
  } catch (e) { $('#matrix').innerHTML = `<tr><td class="s-failed">${e.message}</td></tr>`; return; }
  const pbar = $('#params_note');
  if (pbar) pbar.textContent = raw ? `按参数覆盖看：${raw}` : '';
  const st = state.status;
  // 库来源常驻提示（2026-09-09 教训：漏设 GUJI_WORKSPACE 会静默用仓内示例
  // 库跑批，产物看着 ok 实际全错，事后只能从产物指纹里翻出来）。
  const wsEl = $('#ws_note');
  if (wsEl && st.workspace) {
    const w = st.workspace;
    wsEl.textContent = w.is_sample_db ? '⚠ 用的是仓内示例库（未设 GUJI_WORKSPACE）' : `库：${w.workspace}`;
    wsEl.style.color = w.is_sample_db ? 'var(--zhu, #c00)' : '';
  }
  const pageList = st.pages;
  let html = '<thead><tr><th class="step">步骤</th><th>汇总</th>' + pageList.map(p => `<th>${p}</th>`).join('') + '</tr></thead><tbody>';
  for (const [sid, d] of Object.entries(st.steps)) {
    const c = d.counts;
    html += `<tr><th class="step">${sid}</th><td class="counts"><span class="s-fresh">${c.fresh}</span><span class="s-stale">${c.stale}</span><span class="s-missing">${c.missing}</span><span class="s-failed">${c.failed}</span><span class="s-blocked">${c.blocked}</span></td>`;
    for (const p of pageList) {
      const cell = d.pages[p];
      const t = cell.error ? cell.error : (cell.elapsed != null ? cell.elapsed + 's' : '');
      // 不能用状态首字母：fresh 和 failed 都是 f，颜色之外分不出来（色盲、打印、截图都会栽）
      html += `<td class="cell s-${cell.status}" title="${cell.status}${t ? ' · ' + t : ''}" data-step="${sid}" data-page="${p}">${STATUS_MARK[cell.status] || '?'}</td>`;
    }
    html += '</tr>';
  }
  $('#matrix').innerHTML = html + '</tbody>';
  $('#matrix').querySelectorAll('td.cell').forEach(td => td.onclick = () => { _openProduct(td.dataset.step, td.dataset.page); });
  $('#p_page').innerHTML = pageList.map(p => `<option value="${p}">${p}</option>`).join('');
  $('#running').textContent = st.running ? `运行中：${st.running.id}` : '';
}

export const refresh = refreshStatus;
