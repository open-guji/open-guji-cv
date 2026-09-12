import { api } from './client'
import type { AlignRefSummaryResponse, EvalRunResult, EvalSpec, GateSummaryResponse, OverviewSummaryResponse, RoundResponse, RulersResponse, ThroughputResponse } from '../types/evals'

export const fetchEvals = () => api<EvalSpec[]>('/api/evals')

// 总览页用的轻量摘要，见 console/routers/evals.py::api_overview_summary
// 与 types/evals.ts::OverviewSummaryResponse 模块头。
export const fetchOverviewSummary = (book: string) =>
  api<OverviewSummaryResponse>(`/api/overview_summary?book=${encodeURIComponent(book)}`)

// 已落地的三道交接闸，跟后端 gates/query.py::GATES 的 key 保持一致——
// 若后端新增闸，这里要跟着加，没有反查接口（GATES 是闸 id→(step,kind) 的
// 静态映射，不是运行时数据）。
export const GATE_IDS = ['column_gate', 'row_segment_gate', 'border_detect_gate'] as const

export function fetchGateSummary(book: string, gate: string, pages?: string) {
  const qs = `gate=${encodeURIComponent(gate)}` + (pages ? `&pages=${encodeURIComponent(pages)}` : '')
  return api<GateSummaryResponse>(`/api/gate/${encodeURIComponent(book)}/summary?${qs}`)
}

export function runEval(id: string, timeout = 900) {
  return api<EvalRunResult>(`/api/evals/${encodeURIComponent(id)}/run?timeout=${timeout}`, { method: 'POST' })
}

export function fetchRulers(book: string, pages = 'dev_set') {
  return api<RulersResponse>(`/api/rulers?book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`)
}

export function fetchThroughput(book: string, pages = '') {
  const qs = `book=${encodeURIComponent(book)}` + (pages ? `&pages=${encodeURIComponent(pages)}&all_pages=false` : '')
  return api<ThroughputResponse>(`/api/throughput?${qs}`)
}

export function fetchRound(book: string, pages: string) {
  const qs = `book=${encodeURIComponent(book)}` + (pages ? `&pages=${encodeURIComponent(pages)}` : '')
  return api<RoundResponse>(`/api/round?${qs}`)
}

// 见 console/routers/evals.py::api_align_ref_summary 与 types/evals.ts
// 模块头。留空 pages＝全书，与后端默认口径一致。
export function fetchAlignRefSummary(book: string, pages = '') {
  const qs = `book=${encodeURIComponent(book)}` + (pages ? `&pages=${encodeURIComponent(pages)}` : '')
  return api<AlignRefSummaryResponse>(`/api/align-ref/summary?${qs}`)
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
