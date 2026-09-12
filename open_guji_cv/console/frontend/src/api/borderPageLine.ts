import { api } from './client'
import type { PageLineCardsResponse, PageLineVerdictsResponse } from '../types/borderPageLine'

export function fetchPageLineCards(book: string, pages: string) {
  const qs = `book=${encodeURIComponent(book)}&kind=pageline&pages=${encodeURIComponent(pages)}`
  return api<PageLineCardsResponse>(`/api/border-review/cards?${qs}`)
}

export function fetchPageLineVerdicts(batch: string) {
  return api<PageLineVerdictsResponse>(`/api/border-review/verdicts?batch=${encodeURIComponent(batch)}`)
}
