// 共用底层：$ / api() / fmtDur() / STATUS_MARK。从 index.html 的 <script> 段搬出（C4 前端切分）。
export const $ = (s) => document.querySelector(s);

// 状态记号：形状可辨，不只靠颜色
export const STATUS_MARK = { fresh: '✓', stale: '~', missing: '·', failed: '✗', blocked: '⊘' };

export async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) { let t = await r.text(); try { t = JSON.parse(t).detail || t; } catch (e) {} throw new Error(t); }
  return r.json();
}

export function fmtDur(s) { return s == null ? '' : (s < 60 ? s.toFixed(1) + 's' : (s / 60).toFixed(1) + 'min'); }
