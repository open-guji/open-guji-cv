// main.js：拉注册表、绑 tab、按 {id, mount(root), refresh()} 挂各面板。
// 从 index.html 的 <script> 段搬出（C4 前端切分）。原 init()/showView() 里橫跨多个
// 面板的粘合逻辑（哪个面板要用哪个面板的哪个函数）都收在这里——面板之间不许
// 互相 import，跨面板调用一律由这里在 mount() 时注入。
import { $, api } from './api.js';
import { state, pipeline, toggleView } from './state.js';

import * as overview from './panels/overview.js';
import * as run from './panels/run.js';
import * as products from './panels/products.js';
import * as review from './panels/review.js';
import * as health from './panels/health.js';
import * as harvest from './panels/harvest.js';
import * as cutline from './panels/cutline.js';
import * as jiazhu from './panels/jiazhu.js';
import * as variants from './panels/variants.js';
import * as groups from './panels/groups.js';
import * as evals from './panels/evals.js';

// 按当前所选管线填几处跨面板的下拉与 DAG 图：#from_step/#to_step（运行）、
// #p_step（产物）、#dag/#notes（总览）。四处属于四个不同面板的 DOM，
// 但都是同一份注册表的派生，放在 main.js 里比塞进某一个面板更诚实。
function fillSteps() {
  const p = pipeline(); if (!p) return;
  const opts = p.steps.map(s => `<option value="${s.id}">${s.id} · ${s.title}</option>`).join('');
  $('#from_step').innerHTML = opts; $('#to_step').innerHTML = opts;
  $('#to_step').value = p.steps[p.steps.length - 1].id;
  $('#p_step').innerHTML = opts;
  $('#dag').innerHTML = p.steps.map((s, i) => `<span class="node" title="${s.consumes.join(',')} → ${s.produces.join(',')}">${s.id}</span>` + (i < p.steps.length - 1 ? '<span class="arrow">→</span>' : '')).join('');
  $('#notes').textContent = p.notes || '';
}

function showView(v) {
  toggleView(v);
  // 切到视图时重新拉一次：批次可能是在 CLI 里建的，页面初始化那一次拉不到
  if (v === 'review') harvest.refresh();
  if (v === 'evals') evals.refresh();
  if (v === 'variants') variants.refresh();
  if (v === 'jiazhu') jiazhu.refresh();
}

async function boot() {
  [state.books, state.pipelines] = await Promise.all([api('/api/books'), api('/api/pipelines')]);
  $('#book').innerHTML = state.books.map(b => `<option value="${b.id}">${b.id} · ${b.title}</option>`).join('');
  $('#pipeline').innerHTML = state.pipelines.map(p => `<option value="${p.id}">${p.title}</option>`).join('');
  $('#rv_book').innerHTML = state.books.map(b => `<option value="${b.id}">${b.id}</option>`).join('');
  fillSteps();
  document.querySelectorAll('nav.tabs button').forEach(b => b.onclick = () => showView(b.dataset.view));

  overview.mount(document, { openProduct: (step, page) => products.openProduct(step, page) });
  run.mount(document, { refreshStatus: () => overview.refresh() });
  products.mount(document);
  review.mount(document, { onSubmitted: () => harvest.refresh() });
  health.mount(document, { rvLoad: () => review.refresh() });
  harvest.mount(document, { refreshEvals: () => evals.refresh() });
  cutline.mount(document);
  jiazhu.mount(document);
  variants.mount(document);
  groups.mount(document);
  evals.mount(document);

  $('#refresh').onclick = () => overview.refresh();
  // 状态是**打开时的快照**，后台 CLI 跑完不会自己推过来 —— 实际踩过：
  // CLI 已经重跑完全链，页面还停在旧的一片「过期」，看着像修复没生效。
  // 切回这个标签页时自动重取一次，代价是一个 GET。
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) overview.refresh();
  });
  window.addEventListener('focus', () => overview.refresh());
  $('#pipeline').onchange = () => { fillSteps(); overview.refresh(); };
  $('#book').onchange = () => overview.refresh();

  await overview.refresh();
  run.refresh();
  harvest.refresh();
}

boot();
