// 跨页面借用的领域小工具，对应 v1 static/js/shared/domain.js（原样复用，见方案 §四）。

// 2026-09-26 起没有「读法」：每一格只裁一个字（字形）。己/已/巳 三字刻法不分，裁的就是
// 按上下文定下的那个字（后端 utils/ji_yi_si.py 会给建议，卡片上一键可点）。

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
