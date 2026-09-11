import { api } from './client'
import type { ProductResponse } from '../types/products'

export function fetchProduct(book: string, step: string, page: number) {
  const key = `p${String(page).padStart(4, '0')}`
  return api<ProductResponse>(`/api/products/${encodeURIComponent(book)}/${encodeURIComponent(step)}/${key}`)
}

export function overlayUrl(book: string, step: string, page: number, scale = 0.35) {
  return `/api/overlay/${encodeURIComponent(book)}/${encodeURIComponent(step)}/${page}.png?scale=${scale}&t=${Date.now()}`
}

export interface PrecleanRuleReport {
  kind: string
  segments?: number[][]
  y_lo?: number
  y_hi?: number
  y_probe?: number
  ink_before?: number
  ink_after?: number
  gate?: number
  body_median?: number
  body_p95?: number
  passed?: boolean
}

export interface PrecleanReport {
  page: number
  rules: PrecleanRuleReport[]
  precleaned_exists: boolean
}

export function fetchPrecleanReport(book: string, page: number) {
  return api<PrecleanReport>(`/api/preclean/${encodeURIComponent(book)}/${page}`)
}

export function precleanOverlayUrl(book: string, page: number, scale = 0.5) {
  return `/api/preclean/${encodeURIComponent(book)}/${page}/overlay.png?scale=${scale}&t=${Date.now()}`
}

export function precleanBeforeUrl(book: string, page: number, scale = 0.5) {
  return `/api/preclean/${encodeURIComponent(book)}/${page}/before.png?scale=${scale}&t=${Date.now()}`
}

export function precleanAfterUrl(book: string, page: number, scale = 0.5) {
  return `/api/preclean/${encodeURIComponent(book)}/${page}/after.png?scale=${scale}&t=${Date.now()}`
}

export interface GatePageSummary {
  page: number
  status: 'ok' | 'page_blocked' | 'missing'
  page_reject?: string[]
  n_columns?: number
  n_admitted?: number
  tiers?: string[]
}

export interface GateSummary {
  gate: string
  pages: GatePageSummary[]
  tier_totals: Record<string, number>
}

// Step2 闸2（column_gate）可视化用，见 open_guji_cv/gates/query.py::gate_summary。
export function fetchGateSummary(book: string, gate = 'column_gate') {
  return api<GateSummary>(`/api/gate/${encodeURIComponent(book)}/summary?gate=${encodeURIComponent(gate)}`)
}
