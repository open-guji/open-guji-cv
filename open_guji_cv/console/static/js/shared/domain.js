// 跨面板借用的领域小工具：审查（review）、夹注（jiazhu）、组视图（groups）三个面板都用。
// 面板之间不许互相 import（任务书 §三「约定只有一条」），这两处借用原方案点名要
// 「提到 js/shared/」，故单独成档。从 index.html 的 <script> 段搬出（C4 前端切分）。

// **只有 己/已/巳 这三个字才分「字形」与「文意」**（用户 2026-09-04 定：
// 「除了己已巳 这三个字，其他的都不用区分字形和文意」）。
// 依据是考据结论：已/巳 字源上本是同一个字（段玉裁：地支「巳」久已用为
// 「已然」之「已」），清代刻本包括《欽定四庫全書》本仍混用，古人不当它是错；
// 己 则是真的另一个字，但同样容易与那两个混刻。其余形近家族（諭/論、曾/會…）
// 是**真的不同字**，字形就是释读，多一个输入框只会诱导人把它们也拆开。
// 与 GlyphDB.admit_instance 的 shape/char 分岔、charset_and_lm.md §四 同源。
export const SPLIT_CHARS = new Set(['己', '已', '巳']);
export const needsReading = ch => SPLIT_CHARS.has(ch);

// 释读只认汉字：2026-09-06 审计发现 8 条人裁释读是拼音首字母（l/m/y/x/s/z——输入法没转就提交了），
// 字形是对的。非汉字的释读一律当没填 = 跟随字形。
export const HAN_RE = /[㐀-鿿\u{20000}-\u{3134f}]/u;
export const readingOf = v => (v.reading && HAN_RE.test(v.reading)) ? v.reading : (v.shape || '');

// 提交即消费（POST /api/events 的 consume）：把落库结果拼成一句人话。
// 消费失败不代表裁决丢了——事件已经在盘上，「收割与消费」那块能补跑。
export function consumedMsg(r) {
  if (r.consume_error) return `；⚠ 自动落库失败（${r.consume_error}），去「审查 → 收割与消费」补跑`;
  const c = (r.consumed || []).filter(x => x.added || x.no_lib || (x.errors || []).length);
  if (!c.length) return '；已落库';
  const errs = c.flatMap(x => x.errors || []);
  const noLib = c.reduce((s, x) => s + (x.no_lib || 0), 0);
  return '；已落库（' + c.map(x => `${x.consumer} ${x.added}`).join('，') + '）'
       + (noLib ? `，${noLib} 条按「字形不入库」跳过建库` : '')
       + (errs.length ? ` ⚠ ${errs[0]}` : '');
}
