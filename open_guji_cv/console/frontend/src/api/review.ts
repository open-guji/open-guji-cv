import { api } from './client'
import type {
  AroundContext, RareCandidate, ReviewCardsResponse, ReviewVerdictsResponse,
} from '../types/review'

export function fetchReviewCards(book: string, pages: string, only: string, gateCut: boolean, limit = 400) {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
    + `&only=${only}&gate_cut=${gateCut}&limit=${limit}`
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
  return `/api/review/context-img/${encodeURIComponent(book)}/${page}/${col}/${slot}.png?around=2`
}
