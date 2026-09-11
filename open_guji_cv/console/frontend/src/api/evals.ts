import { api } from './client'
import type { EvalRunResult, EvalSpec, RoundResponse, RulersResponse } from '../types/evals'

export const fetchEvals = () => api<EvalSpec[]>('/api/evals')

export function runEval(id: string, timeout = 900) {
  return api<EvalRunResult>(`/api/evals/${encodeURIComponent(id)}/run?timeout=${timeout}`, { method: 'POST' })
}

export function fetchRulers(book: string, pages = 'dev_set') {
  return api<RulersResponse>(`/api/rulers?book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`)
}

export function fetchRound(book: string, pages: string) {
  const qs = `book=${encodeURIComponent(book)}` + (pages ? `&pages=${encodeURIComponent(pages)}` : '')
  return api<RoundResponse>(`/api/round?${qs}`)
}

export interface RateHistoryRow {
  date: string
  rate: number
  unseen_rate?: number
  note?: string
}

export const fetchRateHistory = (book: string) =>
  api<{ rows: RateHistoryRow[] }>(`/api/review/rate-history?book=${encodeURIComponent(book)}`)

export function postRateSnapshot(books: string, note: string) {
  return api<void>('/api/review/rate-history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ books, note }),
  })
}

export interface QualityResponse {
  accuracy: {
    overall: number
    n_gold: number
    gold_coverage: number
    by_channel: Array<{ channel: string; ok: number; n: number; acc: number }>
    errors: Array<{ id: string; pred: string; gold: string; channel: string }>
  }
  defects: {
    n: number
    by_quality: Array<{ key: string; n: number }>
    by_page: Array<{ key: string; n: number }>
    by_col: Array<{ key: string; n: number }>
    by_slot: Array<{ key: string; n: number }>
  }
}

export const fetchQuality = (book: string, pages: string) =>
  api<QualityResponse>(`/api/quality?book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`)
