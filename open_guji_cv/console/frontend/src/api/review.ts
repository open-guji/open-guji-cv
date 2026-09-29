import { api, withWorkspace } from './client'
import type {
  AroundContext, RareCandidate, ReviewCardsGroupedResponse, ReviewCardsResponse,
  ReviewCardsShapeResponse, ReviewVerdictsResponse,
} from '../types/review'

// `skipDecided`：跳过全书所有批次已裁过的字位（默认开），于是 `limit` 数的是净新卡。
// `doubt`（overview#215）：按 doubt 码筛（`occluded,channel_off`）；`*` = 不筛但要计数
// （响应带 `doubt_counts`）；空串 = 不带这个参数，请求与改前一样。
// `cls`（overview#247）：按类别审，`*` = 不筛只计数（响应带 `class_counts`），类别键 = 只出这一类；
// 空串 = 不带这个参数。
export function fetchReviewCards(book: string, pages: string, only: string, gateCut: boolean,
                                 limit = 400, skipDecided = true, doubt = '', cls = '', clsSub = '') {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
    + `&only=${only}&gate_cut=${gateCut}&limit=${limit}&skip_decided=${skipDecided}`
    + (doubt ? `&doubt=${encodeURIComponent(doubt)}` : '')
    + (cls ? `&cls=${encodeURIComponent(cls)}` : '')
    + (clsSub ? `&cls_sub=${encodeURIComponent(clsSub)}` : '')
  return api<ReviewCardsResponse>(`/api/review/cards?${qs}`)
}

// 按字种批审（`group=char`）：不传 `limit`——这一模式后端本就不按 limit 截断，
// 要的是全量待审格才能如实报每组 n 与页码分布；`sampleLimit` 只管每组样例数。
export function fetchReviewCardsGrouped(book: string, pages: string, only: string, gateCut: boolean,
                                        skipDecided = true, sampleLimit = 60) {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
    + `&only=${only}&gate_cut=${gateCut}&skip_decided=${skipDecided}`
    + `&group=char&sample_limit=${sampleLimit}`
  return api<ReviewCardsGroupedResponse>(`/api/review/cards?${qs}`)
}

// 按形聚类分组（`group=shape`）：先按形近对表把互相混淆的字种池化，池内再用
// CNN embedding 按形状聚类拆开，同样不受 `limit` 截断（理由同 `group=char`）。
export function fetchReviewCardsByShape(book: string, pages: string, only: string, gateCut: boolean,
                                        skipDecided = true, sampleLimit = 60) {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
    + `&only=${only}&gate_cut=${gateCut}&skip_decided=${skipDecided}`
    + `&group=shape&sample_limit=${sampleLimit}`
  return api<ReviewCardsShapeResponse>(`/api/review/cards?${qs}`)
}

export function fetchReviewVerdicts(batch: string) {
  return api<ReviewVerdictsResponse>(`/api/review/verdicts?batch=${encodeURIComponent(batch)}`)
}

export function fetchRareBatch(book: string, k: number, slots: string[]) {
  return api<{ rare: Record<string, RareCandidate[]> }>('/api/rare/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ book, k, slots }),
  })
}

export function fetchRareOne(book: string, page: number, col: number, slot: number, sub?: string) {
  const suffix = sub ? `?sub=${encodeURIComponent(sub)}&k=10` : '?k=10'
  return api<{ candidates: RareCandidate[] }>(`/api/rare/${encodeURIComponent(book)}/${page}/${col}/${slot}${suffix}`)
}

/** IDS 兜底：按结构 + 认出的部件查字（/api/rare/search）。给了字位坐标就用那格的 emb 在池内排。 */
export function fetchRareSearch(book: string, q: {
  top?: string; slots?: Record<string, string>; comps?: string[];
  page?: number; col?: number; cell?: number; sub?: string; k?: number
}) {
  const sp = new URLSearchParams()
  if (q.top) sp.set('top', q.top)
  for (const [slot, comp] of Object.entries(q.slots || {})) if (comp) sp.append('slot', `${slot}=${comp}`)
  for (const c of q.comps || []) if (c) sp.append('comp', c)
  if (q.page) { sp.set('page', String(q.page)); sp.set('col', String(q.col || 0)); sp.set('cell', String(q.cell || 0)) }
  if (q.sub) sp.set('sub', q.sub)
  sp.set('k', String(q.k ?? 10))
  return api<{ candidates: RareCandidate[]; with_image: boolean }>(
    `/api/rare/search/${encodeURIComponent(book)}?${sp.toString()}`)
}

export function fetchAroundBatch(
  book: string, before: number, after: number,
  // 带非空 `sub` 的项，返回键是 `p:c:s<sub>`（夹注 a/b 各一份），见 `aroundKey`
  items: Array<{ page: number; col: number; slot: number; sub?: string }>,
) {
  return api<{ around: Record<string, AroundContext> }>('/api/review/around/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ book, before, after, items }),
  })
}

export function contextImgUrl(book: string, page: number, col: number, slot: number) {
  return withWorkspace(`/api/review/context-img/${encodeURIComponent(book)}/${page}/${col}/${slot}.png?around=2`)
}

/** 字体候选索引状态（K19，`GET /api/rare/status`）：`deferred` = 缺盘且有活跑批，冷建推迟，
 * 这段时间字体候选（HOG 那一路）不可用；库/CNN 两路不受影响。 */
export const fetchRareStatus = () => api<{ deferred?: boolean; [k: string]: unknown }>('/api/rare/status')

/** `fetchAroundBatch` 返回值的键：与后端 `api_review_around_batch` 同一口径。 */
export function aroundKey(c: { page: number; col: number; slot: number; sub?: string }) {
  return `${c.page}:${c.col}:${c.slot}${c.sub || ''}`
}
