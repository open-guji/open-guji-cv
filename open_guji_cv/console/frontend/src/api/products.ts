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

export interface AlignRefPageSummary {
  page: number
  status: 'anchored' | 'not_anchored' | 'missing'
  n_chars?: number
  note?: string
  n_grams?: number
  n_votes?: number
  vote_frac?: number
  dominance?: number | null
}

export interface AlignRefSummary {
  pages: AlignRefPageSummary[]
  n_pages: number
  n_anchored: number
  n_missing: number
  n_not_anchored: number
}

// Step5-d 整理本对齐可视化用，见 open_guji_cv/steps/align_ref.py::align_ref_summary。
// 不是闸，不经过 fetchGateSummary 那套（不拦截，只上报证据可用性）。
export function fetchAlignRefSummary(book: string, pages?: string) {
  const q = pages ? `?pages=${encodeURIComponent(pages)}` : ''
  return api<AlignRefSummary>(`/api/align-ref/${encodeURIComponent(book)}/summary${q}`)
}

export interface OcrCandidatesSummary {
  n_pages: number
  n_missing: number
  n_unavailable: number
  engines: Record<string, number>
  n_chars: number
  n_with_candidates: number
  coverage: number | null
}

// Step5-c OCR 候选板块②聚合数字（引擎在线状态+候选覆盖率），见
// open_guji_cv/steps/ocr_candidates.py::ocr_candidates_summary。07号任务卡
// 判断这一路不需要独立查询页，此接口只服务聚合数字。
export function fetchOcrCandidatesSummary(book: string, pages?: string) {
  const q = pages ? `?pages=${encodeURIComponent(pages)}` : ''
  return api<OcrCandidatesSummary>(`/api/ocr-candidates/${encodeURIComponent(book)}/summary${q}`)
}
