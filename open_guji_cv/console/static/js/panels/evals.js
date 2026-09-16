// ── 评测 ───────────────────────────────────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。
import { $, api } from '../api.js';

export const id = 'evals';

export function mount(root) {}

const evalState = {};

export async function loadEvals() {
  let list = [];
  try { list = await api('/api/evals'); } catch (e) { $('#ev_msg').textContent = e.message; return; }
  $('#evtbl').innerHTML = list.map(s => {
    const r = evalState[s.id];
    const badge = r ? `<span class="badge b-${r.status === 'ok' ? 'completed' : (r.status === 'regressed' ? 'running' : 'failed')}">${r.status}</span>`
                    : (s.runnable ? '<span class="muted">未跑</span>' : `<span class="muted">${s.blocked}</span>`);
    const ms = r ? (r.metrics || []).slice(0, 2).map(m => `${m.name} ${m.value}${m.unit || ''}`).join('，') : '';
    const gold = r && r.n_gold != null ? `${r.n_gold}${r.stale_gold ? ` (过期 ${r.stale_gold})` : ''}` : '';
    return `<tr><td class="mono">${s.id}</td><td class="mono">${s.shard}</td><td>${badge}</td>
      <td class="mono">${ms}</td><td class="mono">${gold}</td>
      <td>${s.runnable ? `<button data-ev="${s.id}">跑</button>` : ''}</td></tr>`;
  }).join('');
  $('#evtbl').querySelectorAll('button[data-ev]').forEach(b => b.onclick = () => runOneEval(b.dataset.ev));
  $('#ev_all').onclick = async () => {
    const runnables = list.filter(s => s.runnable);
    $('#ev_msg').textContent = `跑 ${runnables.length} 个…`;
    for (const s of runnables) await runOneEval(s.id, true);
    $('#ev_msg').textContent = '完成';
  };
}

async function runOneEval(id, quiet) {
  if (!quiet) $('#ev_msg').textContent = `${id} 跑中…`;
  try {
    const r = await api(`/api/evals/${id}/run`, { method: 'POST' });
    evalState[id] = r;
    $('#evout').textContent = JSON.stringify(r, null, 1).slice(0, 4000);
    loadEvals();
  } catch (e) { $('#evout').textContent = `${id}: ${e.message}`; }
  if (!quiet) $('#ev_msg').textContent = '';
}

export const refresh = loadEvals;
