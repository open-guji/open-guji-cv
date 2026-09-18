import { api } from './client'

export interface SlotCountCard {
  id: string
  kind: 'slot-count'
  book: string
  page: number
  col: number
  det_n_slots: number | null
  det_ok: boolean | null
  img: string
}

export function fetchSlotCountCards(book: string, pages: string) {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
  return api<{ book: string; pages: number[]; n: number; cards: SlotCountCard[] }>(
    `/api/slot-count-review/cards?${qs}`)
}

export interface SlotCountVerdictRow {
  n_slots: number
}

export function fetchSlotCountVerdicts(batch: string) {
  return api<{ batch: string; verdicts: Record<string, SlotCountVerdictRow> }>(
    `/api/slot-count-review/verdicts?batch=${encodeURIComponent(batch)}`)
}
