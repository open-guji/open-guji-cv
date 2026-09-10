// ── 收割与消费：批次 / 事件 / 金标摘要 ────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。载入批次后要顺带刷新
// 「评测」面板——那是另一个面板，按约定不直接 import，由 mount() 的 deps 转接。
import { $, api } from '../api.js';

export const id = 'review';

let _refreshEvals = () => {};

export function mount(root, deps = {}) {
  if (deps.refreshEvals) _refreshEvals = deps.refreshEvals;
  $('#h_go').onclick = doHarvest;
  $('#r_go').onclick = () => doRoute(false);
  $('#r_dry').onclick = () => doRoute(true);
}

// ── 审查 ───────────────────────────────────────────────────────────
export async function loadBatches() {
  let bs = [];
  try { bs = await api('/api/batches'); } catch (e) { $('#bmsg').textContent = e.message; }
  $('#batches').innerHTML = bs.length ? bs.map(b => `<tr>
    <td class="mono">${b.id}</td><td>${b.title}</td><td class="mono">${b.step}</td>
    <td>${b.transport}${b.url ? ` <a href="${b.url}" target="_blank" rel="noopener">链接</a>` : ''}</td>
    <td class="mono">${b.n_cards}</td><td class="mono">${b.n_events}</td><td class="mono">${b.n_consumed}</td>
    <td><span class="badge b-${b.status === 'harvested' ? 'completed' : (b.status === 'open' ? 'running' : 'pending')}">${b.status}</span></td>
    <td><button data-route="${b.id}">消费</button></td></tr>`).join('')
    : '<tr><td colspan="9" class="muted">还没有批次。用 CLI 建：guji-cv batch new …</td></tr>';
  $('#batches').querySelectorAll('button[data-route]').forEach(x => x.onclick = () => { $('#h_batch').value = x.dataset.route; doRoute(false); });
  $('#h_batch').innerHTML = bs.map(b => `<option value="${b.id}">${b.id}</option>`).join('');
  loadGold();
  _refreshEvals();
}

async function loadGold() {
  let shards = [];
  try { shards = (await api('/api/gold')).shards; } catch (e) { $('#goldout').textContent = e.message; return; }
  $('#goldtbl').innerHTML = shards.map(s => {
    const st = Object.entries(s.status || {}).map(([k, v]) => `${k} ${v}`).join(' / ');
    const str = Object.entries(s.stratum || {}).map(([k, v]) => `${k} ${v}`).join(' / ') || '—';
    const migrated = s.carrier === 'items';
    return `<tr><td class="mono">${s.shard}</td>
      <td><span class="badge b-${migrated ? 'completed' : 'pending'}">${s.carrier}</span></td>
      <td class="mono">${s.n}</td><td class="mono">${st}</td><td class="mono">${str}</td>
      <td>${migrated ? `<button data-drift="${s.shard}">漂移检查</button>` : `<button data-mig="${s.shard}">迁移</button>`}</td></tr>`;
  }).join('');
  $('#goldtbl').querySelectorAll('button[data-mig]').forEach(b => b.onclick = async () => {
    try { $('#goldout').textContent = JSON.stringify(await api(`/api/gold/${b.dataset.mig}/migrate`, { method: 'POST' }), null, 1); loadGold(); }
    catch (e) { $('#goldout').textContent = e.message; }
  });
  $('#goldtbl').querySelectorAll('button[data-drift]').forEach(b => b.onclick = async () => {
    $('#goldout').textContent = '检查中…';
    try { $('#goldout').textContent = JSON.stringify(await api(`/api/gold/${b.dataset.drift}/drift`, { method: 'POST' }), null, 1); }
    catch (e) { $('#goldout').textContent = e.message; }
  });
}

async function doHarvest() {
  const batch = $('#h_batch').value, text = $('#h_text').value.trim();
  if (!batch || !text) { $('#h_out').textContent = '选批次、贴内容'; return; }
  const bs = await api('/api/batches');
  const b = bs.find(x => x.id === batch);
  try {
    const r = await api(`/api/batches/${batch}/harvest`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch, step: b ? b.step : '', kind: b ? b.kind : 'verdict', content: text }) });
    $('#h_out').textContent = JSON.stringify(r, null, 1);
    loadBatches();
  } catch (e) { $('#h_out').textContent = '收割失败：' + e.message; }
}

async function doRoute(dry) {
  const batch = $('#h_batch').value;
  if (!batch) return;
  try {
    const r = await api(`/api/batches/${batch}/route?dry_run=${dry}`, { method: 'POST' });
    $('#h_out').textContent = JSON.stringify(r, null, 1);
    loadBatches();
  } catch (e) { $('#h_out').textContent = '消费失败：' + e.message; }
}

export const refresh = loadBatches;
