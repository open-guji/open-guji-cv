// ── 运行 ───────────────────────────────────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。跑完/取消后要刷新总览的状态矩阵——
// 那是另一个面板，按约定不直接 import，由 mount() 的 deps 转接。
import { $, api, fmtDur } from '../api.js';
import { state } from '../state.js';

export const id = 'run';

let _refreshStatus = () => {};

export function mount(root, deps = {}) {
  if (deps.refreshStatus) _refreshStatus = deps.refreshStatus;
  $('#runform').onsubmit = submitRun;
}

export async function submitRun(ev) {
  ev.preventDefault();
  let params = {};
  const raw = $('#params').value.trim();
  if (raw) { try { params = JSON.parse(raw); } catch (e) { $('#runmsg').textContent = '参数 JSON 不合法：' + e.message; return; } }
  // 空下拉框的 `.value` 是 `''`，不是 `null`——直接传给后端，`pipeline.slice('', '')`
  // 会把 '' 当真步骤名去查，查不到就报「没有步骤 ''」（2026-09-09 用户实锤）。
  // 后端按 `from_step is None` 判「不设下限」，所以空值这里就该转成 null。
  const body = { book: $('#book').value, pipeline: $('#pipeline').value,
    from_step: $('#from_step').value || null, to_step: $('#to_step').value || null,
    pages: $('#run_pages').value || 'dev_set', force: $('#force').checked, params,
    allow_sample_db: $('#allow_sample_db').checked };
  try {
    const job = await api('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    $('#runmsg').textContent = `已入队 ${job.id}`;
    await pollJobs(); selectJob(job.id);
  } catch (e) { $('#runmsg').textContent = '入队失败：' + e.message; }
}

export async function pollJobs() {
  try { state.jobs = await api('/api/runs?limit=30'); } catch (e) { return; }
  const tb = $('#jobs');
  tb.innerHTML = state.jobs.map(j => `<tr class="${j.id === state.selJob ? 'sel' : ''}" data-id="${j.id}">
    <td class="mono">${j.id.slice(4)}</td><td>${j.spec.book} / ${j.spec.pipeline}</td>
    <td class="mono">${j.spec.from_step || '首'} → ${j.spec.to_step || '末'}${j.spec.force ? ' !' : ''}</td>
    <td class="mono">${j.spec.pages}</td><td><span class="badge b-${j.status}">${j.status}</span></td>
    <td class="mono">${fmtDur(j.duration)}</td>
    <td>${['pending', 'running'].includes(j.status) ? `<button class="danger" data-cancel="${j.id}">取消</button>` : ''}</td></tr>`).join('');
  tb.querySelectorAll('tr').forEach(tr => tr.onclick = (e) => { if (e.target.dataset.cancel) return; selectJob(tr.dataset.id); });
  tb.querySelectorAll('button[data-cancel]').forEach(b => b.onclick = async () => { await api(`/api/runs/${b.dataset.cancel}/cancel`, { method: 'POST' }); pollJobs(); });
  const active = state.jobs.some(j => ['pending', 'running'].includes(j.status));
  $('#running').textContent = active ? '有任务在跑' : '';
  setTimeout(pollJobs, active ? 2000 : 8000);
}

export function selectJob(id) {
  if (state.es) { state.es.close(); state.es = null; }
  state.selJob = id;
  $('#logtitle').textContent = id;
  const pre = $('#log'); pre.textContent = '';
  const es = new EventSource(`/api/runs/${id}/log`);
  state.es = es;
  es.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.type === 'line') {
      const span = document.createElement('span');
      span.textContent = d.line + '\n';
      if (/失败|阻塞|Error|Traceback/.test(d.line)) span.className = 'fail';
      else if (/完成/.test(d.line)) span.className = 'ok';
      else if (/跳过/.test(d.line)) span.className = 'skip';
      pre.appendChild(span); pre.scrollTop = pre.scrollHeight;
    } else if (d.type === 'complete') {
      const span = document.createElement('span'); span.className = d.status === 'completed' ? 'ok' : 'fail';
      span.textContent = `— ${d.status}，退出码 ${d.exit_code}，${fmtDur(d.duration)} —\n`;
      pre.appendChild(span); es.close(); state.es = null; _refreshStatus(); pollJobs();
    }
  };
  pollJobs();
}

export const refresh = pollJobs;
