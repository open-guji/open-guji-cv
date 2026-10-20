import type { ReviewCard } from '../../types/review'

/** 相似字缺省展开几个（用户 2026-10-19 定）。 */
export const ALT_SHOW = 10

/** 卡上的近似字（与后端 `review/alt_cands.pivots_of` 同一个优先级）：整理本字 → 惯刻形 → 上下文字 →
 * 库前 3 → 义定形未定的组内形 → 己已巳建议 → 遮挡默认字。 */
export function cardPivots(c: ReviewCard): string[] {
  const out: string[] = []
  const put = (x?: string | null) => { if (x && [...x].length === 1 && !out.includes(x)) out.push(x) }
  put(c.ref?.char); put(c.ref?.form); put(c.ctx?.char); put(c.ctx?.llm_suggestion)
  for (const [ch] of (c.db?.candidates || []).slice(0, 3)) put(ch)
  for (const f of c.form?.forms || []) put(f)
  put(c.jys?.char); put(c.occluded?.char)
  return out
}
