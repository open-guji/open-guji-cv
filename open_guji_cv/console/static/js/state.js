// 全局状态与视图切换基础设施。从 index.html 的 <script> 段搬出（C4 前端切分）。
import { $ } from './api.js';

export const state = { books: [], pipelines: [], status: null, jobs: [], es: null, selJob: null };

export function pipeline() { return state.pipelines.find(p => p.id === $('#pipeline').value); }

// 纯 DOM 切换：只管哪个 <section>/tab 是 active。
// 切到某个 tab 时要不要顺带重新拉数据，由 main.js 的 showView() 决定
// （原 showView 把两件事绑在一起；面板之间不许互相 import，拆成这一半留在 shared）。
export function toggleView(v) {
  document.querySelectorAll('.view').forEach(x => x.classList.toggle('active', x.id === 'view-' + v));
  document.querySelectorAll('nav.tabs button').forEach(b => b.classList.toggle('active', b.dataset.view === v));
}
