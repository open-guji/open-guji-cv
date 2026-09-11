import { api } from './client'
import type { CutlineCasesResponse, CutlineVerdictsResponse } from '../types/cutline'

export function fetchCutlineCases(
  book: string, pages: string, limit: number, batch: string, skipDone: boolean, kind: string,
  scope: 'all' | 'blocking' = 'all',
) {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
    + `&limit=${limit}&batch=${encodeURIComponent(batch)}&skip_done=${skipDone}`
    + `&kind=${encodeURIComponent(kind)}&scope=${scope}`
  return api<CutlineCasesResponse>(`/api/cutline/cases?${qs}`)
}

export function fetchCutlineVerdicts(batch: string) {
  return api<CutlineVerdictsResponse>(`/api/cutline/verdicts?batch=${encodeURIComponent(batch)}`)
}
