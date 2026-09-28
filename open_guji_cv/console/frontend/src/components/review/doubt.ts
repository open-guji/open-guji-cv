import type { ReviewCard } from '../../types/review'
import type { Verdict } from './ReviewPanel'

// 待审卡按 doubt 码筛选（overview#215）。后端 `/api/review/cards?doubt=…` 给计数与筛选，
// 这里只放中文名与「印章遮挡整组确认」的事件展开（纯函数，好测）。

/** doubt 码 → 按钮上的中文名。没列到的码按原码显示（新闸加了码，这里忘了补也不至于看不见）。 */
export const DOUBT_NAMES: Record<string, string> = {
  occluded: '印章遮挡',
  channel_off: '通道已关',
  replace_form: '换字取形',
  variant_indirect: '异体间接',
  solo_confusable: '单证形近',
  near_form: '形近家族',
  replace_align: '对齐改字层',
  form_open: '义定形未定',
  ref_lib_variant: '库形异体',
  iron_vs_ref: '铁证≠整理本',
  context_vs_ref: '上下文≠整理本',
  context_verdict: '上下文档外',
  context_blank_cell: '空白字块',
  ji_yi_si_review: '己已巳',
  signal_conflict: '信号冲突',
  weak_single: '单信号弱',
  degraded_crop: '图块残缺',
  db_inconsistent: '与库不符',
  _none: '无闸码',
}

/** 按钮悬停说明：这个码是哪道闸打回来的。 */
export const DOUBT_HINTS: Record<string, string> = {
  occluded: '印章／大片污损遮挡（#195）：默认填整理本字、字形不入库，确认一下即可，可整组一键确认',
  channel_off: '本书关掉的放行通道（书 yaml off_channels，#155）判的字，作废后落人审',
  replace_form: 'match_replace 放行时库形与整理本字字面不同（#155 replace_form=review）',
  variant_indirect: '库形与整理本只经第三个字间接成异体，没有直接边（#178）',
  solo_confusable: '只有形状一条证据、库首选又在形近表里（#155）',
  _none: '没有任何 doubt 码（只有库 unsure／上下文 margin 不足这类说明）',
}

export const doubtName = (code: string) => DOUBT_NAMES[code] ?? code

/** 卡片默认裁决：印章遮挡卡在 `load()` 里预填的那份（整理本字 / 假格非字）。缺默认字返回 null。 */
export function occludedDefault(c: ReviewCard, now: number): Verdict | null {
  const o = c.occluded
  if (!o) return null
  if (o.ref_blank) return { shape: '', done: 'non', ts: now }
  if (!o.char) return null
  return { shape: o.char, done: '1', ts: now, noGlyphLib: true }
}

/**
 * 印章遮挡整组确认 → 事件行（与 #166 按簇提交同一机制：一组展开成 N 条逐格事件，
 * 每行带 `via` 与组大小，走既有 `POST /api/events`，不新造协议）。
 *
 * 每格用**人在这一屏上的当前裁决**（改过就用改过的），没有就用默认（整理本字／非字）。
 * 字形一律不入库（`no_glyph_lib: true`，#195「这些格太脏」）。既没默认字、人也没填的
 * 格不提交，留在待审——返回值 `skipped` 里报出来。
 */
export function occludedGroupRows(cards: ReviewCard[], verdicts: Record<string, Verdict | undefined>,
                                  now: number) {
  const occ = cards.filter((c) => c.occluded)
  const rows: Array<Record<string, unknown>> = []
  const skipped: string[] = []
  const via = { via: 'doubt:occluded', group_n: occ.length }
  for (const c of occ) {
    const v = (verdicts[c.id]?.done ? verdicts[c.id] : null) ?? occludedDefault(c, now)
    if (!v || !v.done || v.done === 'skip') { skipped.push(c.id); continue }
    if (v.done === 'non') { rows.push({ id: c.id, v: 'not_a_char', ...via }); continue }
    if (v.done === 'damaged') {
      rows.push({ id: c.id, v: 'damaged', guess: v.guess || '', client_ts: v.ts ?? now, ...via })
      continue
    }
    if (v.done === 'truncated' || v.done === 'contaminated') {
      rows.push({ id: c.id, v: 'seg_defect', quality: v.done, shape: v.shape || '',
                  client_ts: v.ts ?? now, ...via })
      continue
    }
    if (!v.shape) { skipped.push(c.id); continue }
    rows.push({ id: c.id, v: 'confirm', shape: v.shape, no_glyph_lib: true,
                client_ts: v.ts ?? now, ...via })
  }
  return { rows, skipped }
}
