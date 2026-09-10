// ── 产物 ───────────────────────────────────────────────────────────
// 从 index.html 的 <script> 段搬出（C4 前端切分）。
import { $, api } from '../api.js';
import { toggleView } from '../state.js';

export const id = 'products';

export function mount(root) {
  $('#p_load').onclick = loadProduct;
}

export function openProduct(step, page) {
  // 页号下拉由 refreshStatus 填；跨册切换后可能还没有这一页，补一个再选，
  // 否则 value 赋不上、下拉显示的步骤与实际加载的对不上。
  const sel = $('#p_page');
  if (![...sel.options].some(o => o.value === String(page))) {
    sel.insertAdjacentHTML('beforeend', `<option value="${page}">${page}</option>`);
  }
  $('#p_step').value = step;
  sel.value = String(page);
  toggleView('products');
  loadProduct();
}

export async function loadProduct() {
  const book = $('#book').value, step = $('#p_step').value, page = $('#p_page').value;
  if (!page) return;
  const key = 'p' + String(page).padStart(4, '0');
  $('#p_img').src = `/api/overlay/${book}/${step}/${page}.png?scale=0.35&t=${Date.now()}`;
  try {
    const d = await api(`/api/products/${book}/${step}/${key}`);
    const m = d.manifest || {};
    $('#p_meta').textContent = `${key} · 指纹 ${m.fingerprint || '-'} · ${m.status || ''} · ${m.elapsed != null ? m.elapsed + 's' : ''} · ${fmtTs(m.ts)} · ${m.code_rev || ''}`;
    $('#p_json').textContent = JSON.stringify(d.products, null, 1);
  } catch (e) { $('#p_meta').textContent = ''; $('#p_json').textContent = e.message; }
}

/** 产物时间戳（秒）→ 本地时间；没有就不显示。跑完一眼能看出产物是几时的。 */
function fmtTs(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const refresh = loadProduct;
