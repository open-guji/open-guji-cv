import { api } from './client'
import type { BorderReviewCardsResponse, BorderReviewKind, BorderReviewVerdictsResponse } from '../types/borderReview'

export function fetchBorderReviewCards(book: string, kind: BorderReviewKind, pages: string) {
  const qs = `book=${encodeURIComponent(book)}&kind=${kind}&pages=${encodeURIComponent(pages)}`
  return api<BorderReviewCardsResponse>(`/api/border-review/cards?${qs}`)
}

export function fetchBorderReviewVerdicts(batch: string) {
  return api<BorderReviewVerdictsResponse>(`/api/border-review/verdicts?batch=${encodeURIComponent(batch)}`)
}
