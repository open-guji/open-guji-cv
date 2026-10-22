import { api, withWorkspace } from './client'

/** Step0 反色带候选的审卡（`console/routers/invert_review.py`，2026-10-22）。 */
export interface InvertBand {
  bbox: [number, number, number, number]
  flipped_rules: number
  ink: number
  rule: Record<string, unknown>
}

export interface InvertCard {
  id: string
  page: number
  question: string
  bands: InvertBand[]
  rules: Array<Record<string, unknown>>
  verdict: 'yes' | 'no' | null
}

export function fetchInvertCards(book: string, decided = false) {
  return api<{ n: number; cards: InvertCard[] }>(
    `/api/invert-review/cards?book=${encodeURIComponent(book)}&pages=all&decided=${decided}`)
}

export function invertPreviewUrl(book: string, page: number, which: 'before' | 'after') {
  return withWorkspace(`/api/invert-review/preview?book=${encodeURIComponent(book)}&page=${page}&which=${which}`)
}
