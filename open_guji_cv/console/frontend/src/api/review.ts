import { api, withWorkspace } from './client'
import type {
  AroundContext, RareCandidate, ReviewCardsResponse, ReviewVerdictsResponse,
} from '../types/review'

// `skipDecided`：跳过全书所有批次已裁过的字位（默认开），于是 `limit` 数的是净新卡。
export function fetchReviewCards(book: string, pages: string, only: string, gateCut: boolean,
                                 limit = 400, skipDecided = true) {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
    + `&only=${only}&gate_cut=${gateCut}&limit=${limit}&skip_decided=${skipDecided}`
  return api<ReviewCardsResponse>(`/api/review/cards?${qs}`)
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
  book: string, before: number, after: number, items: Array<{ page: number; col: number; slot: number }>,
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
