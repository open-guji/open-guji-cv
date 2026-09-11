// 跨页面借用的领域小工具，对应 v1 static/js/shared/domain.js（原样复用，见方案 §四）。

// 只有 己/已/巳 这三个字才分"字形"与"文意"（用户 2026-09-04 定，理由见 v1 domain.js 注释）。
export const SPLIT_CHARS = new Set(['己', '已', '巳'])
export const needsReading = (ch: string) => SPLIT_CHARS.has(ch)

const HAN_RE = /[㐀-鿿\u{20000}-\u{3134f}]/u
export const readingOf = (v: { reading?: string; shape?: string }) =>
  v.reading && HAN_RE.test(v.reading) ? v.reading : v.shape || ''

export interface ConsumeResult {
  consume_error?: string
  consumed?: Array<{ consumer: string; added: number; no_lib?: number; errors?: string[] }>
}

export function consumedMsg(r: ConsumeResult): string {
  if (r.consume_error) return `；⚠ 自动落库失败（${r.consume_error}），去「审查 → 收割与消费」补跑`
  const c = (r.consumed || []).filter((x) => x.added || x.no_lib || (x.errors || []).length)
  if (!c.length) return '；已落库'
  const errs = c.flatMap((x) => x.errors || [])
  const noLib = c.reduce((s, x) => s + (x.no_lib || 0), 0)
  return (
    '；已落库（' + c.map((x) => `${x.consumer} ${x.added}`).join('，') + '）' +
    (noLib ? `，${noLib} 条按「字形不入库」跳过建库` : '') +
    (errs.length ? ` ⚠ ${errs[0]}` : '')
  )
}
