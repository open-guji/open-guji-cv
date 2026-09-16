// 跨页面借用的领域小工具，对应 v1 static/js/shared/domain.js（原样复用，见方案 §四）。

// 曾经只有 己/已/巳 才分"字形"与"文意"两个输入框（用户 2026-09-04 定，理由见 v1
// domain.js 注释）。用户 2026-09-11 改口：这三个字的判定与人工确认都只看文意，字形
// 库也不再为它们分岔存储样本（见 open_guji_cv/clustering/glyph_db.py 的
// CONFUSABLE_SAMPLE_CAP）——两个框收窄成一个，`needsReading` 永远返回 false。
// 留着这个函数（而不是删掉三处调用点）是为了给以后别的易混字组复用同一个开关；
// 真要加新组时改这里就够，不用再碰 ReviewCardView/ReviewPanel/GroupsPanel/JiazhuPanel。
export const needsReading = (_ch: string) => false

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
