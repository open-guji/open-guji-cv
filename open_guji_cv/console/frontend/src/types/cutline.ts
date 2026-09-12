// 对应 GET /api/cutline/cases 与 /api/cutline/verdicts，字段照
// v1 static/js/panels/cutline.js 的用法反推（原样复用后端契约，见方案 §一）。

export interface CandidateMatch {
  verdict: 'same' | 'unsure' | 'diff' | string
  char: string | null
  cov: number
  wmax: number
  // unsure 档没有单一 char 时的候选池（字, cov），降序，最多 3 个
  // （overview 2026-09-11 下发：char 为 null 不该只显示问号）
  candidates?: Array<[string, number]>
}

export interface CutCandidate {
  kind: 'straight' | 'seam_narrow' | 'seam_wide' | string
  y: number[] | null
  seam_ink: number
  dev_max: number
  // 选这个切法，上格/下格库匹配认出的字（overview 2026-09-11 下发）。
  // null = 没跑过 Step4/5 或没有匹配结果，前端按"无识别信息"处理。
  match_above?: CandidateMatch | null
  match_below?: CandidateMatch | null
}

export interface CutlineCase {
  id: string
  page: number
  col: number
  bi: number
  ink: number
  y: number
  y0: number
  y1: number
  x0: number
  x1: number
  col_w?: number
  col_h: number
  crop_y0: number
  crop_y1: number
  img: string
  seam?: number[] | null
  candidates: CutCandidate[]
  chosen: number | null
  slot_above: number
  slot_below: number
  char_above?: string
  char_below?: string
}

export interface CutlineCasesResponse {
  book: string
  pages: number[]
  n_r2s: number
  n_done: number
  n: number
  cases: CutlineCase[]
}

export interface CutlineVerdict {
  verdict: string
  y?: number
  polyline?: Array<[number, number]>
  cand?: string
}

export interface CutlineVerdictsResponse {
  verdicts: Record<string, CutlineVerdict>
}
