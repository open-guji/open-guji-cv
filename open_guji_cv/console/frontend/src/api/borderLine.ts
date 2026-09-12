import { api } from './client'
import type { BorderLineCardsResponse, BorderLineVerdictsResponse } from '../types/borderLine'

export function fetchBorderLineCards(book: string, pages: string) {
  const qs = `book=${encodeURIComponent(book)}&kind=linebot&pages=${encodeURIComponent(pages)}`
  return api<BorderLineCardsResponse>(`/api/border-review/cards?${qs}`)
}

export function fetchBorderLineVerdicts(batch: string) {
  return api<BorderLineVerdictsResponse>(`/api/border-review/verdicts?batch=${encodeURIComponent(batch)}`)
}
