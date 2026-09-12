// 对应 GET /api/evals、POST /api/evals/{id}/run，字段照
// v1 static/js/panels/evals.js 的用法反推（原样复用后端契约）。

export interface EvalSpec {
  id: string
  shard: string
  title: string
  note?: string
  runnable: boolean
  blocked?: string
  needs: string[]
}

export interface EvalRunResult {
  status: 'ok' | 'regressed' | string
  metrics?: Array<{ name: string; value: number; unit?: string }>
  n_gold?: number
  stale_gold?: number
  [k: string]: unknown
}

export interface RulerRow {
  key: string
  title: string
  note: string
  value: number | null
  unit: string
  num: number
  den: number
  goal: string
  detail?: Array<{ page: number; col?: number; slot?: number; px?: number }>
}

export interface RulersResponse {
  rulers: RulerRow[]
}

export interface RoundLight {
  light: 'green' | 'yellow' | 'red' | 'none'
}

// 对应 GET /api/throughput（`eval/throughput.py`）。只读现有产物聚合的
// statistics 三件套：逐页输入输出 / 通道占比 / performance。
export interface ThroughputPage {
  page: number
  n_total: number
  n_auto: number
  n_review: number
  n_excluded: number
  review_rate: number | null
}

export interface ThroughputChannel {
  channel: string
  n: number
  pct: number
}

export interface ThroughputStepTiming {
  step: string
  n_pages: number
  mean_s?: number
  median_s?: number
  p90_s?: number
  total_s?: number
}

export interface ThroughputResponse {
  per_page: { book: string; pages: ThroughputPage[] }
  channels: { book: string; total_auto: number; channels: ThroughputChannel[] }
  timing: { book: string; steps: ThroughputStepTiming[] }
}

// 对应 GET /api/gate/{book}/summary（console/routers/products.py::api_gate_summary，
// 引擎在 gates/query.py::gate_summary）。三道闸（GATE_IDS）共用同一形状。
export interface GateSummaryPageRow {
  page: number
  status: 'ok' | 'page_blocked' | 'missing'
  page_reject?: string[]
  n_columns?: number
  n_admitted?: number
  tiers?: string[]
  flags?: string[]
  n_cols?: number | null
  expected_cols?: number | null
  page_type?: string | null
  page_type_policy?: string | null
}

export interface GateSummaryResponse {
  gate: string
  pages: GateSummaryPageRow[]
  tier_totals: Record<string, number>
}

// 对应 GET /api/align-ref/summary（console/routers/evals.py::api_align_ref_summary，
// 领域逻辑在 steps/align_ref.py::align_ref_summary）。不是闸——四路证据里
// 任一路缺席只降级不阻塞，这里只是把"哪页锚不上、卡在哪条判据"列出来。
export interface AlignRefPageRow {
  page: number
  status: 'anchored' | 'not_anchored' | 'missing'
  n_chars?: number
  note?: string
  n_grams?: number
  n_votes?: number
  vote_frac?: number | null
  dominance?: number | null
}

export interface AlignRefSummaryResponse {
  pages: AlignRefPageRow[]
  n_pages: number
  n_anchored: number
  n_missing: number
  n_not_anchored: number
}

// 对应 GET /api/overview_summary（console/routers/evals.py::api_overview_summary）。
// 总览页 2026-09-11 重构用的轻量摘要：总进度（另走 fetchStatus）之外的
// 待办 + 异常数据，字段照后端 dict 原样反推。
export interface OverviewSummaryResponse {
  book: string
  rate: {
    rate?: number | null
    review?: number
    slots?: number
    unseen_rate?: number | null
    [k: string]: unknown
  }
  next: { body_total: number; done: number; todo: number; batch: number[]; error?: string }
  gates: Array<{ gate: string; n_pages: number; n_blocked: number; tier_totals: Record<string, number> }>
  align_ref: { n_pages: number; n_anchored: number; n_not_anchored: number; n_missing: number }
}

export interface RoundResponse {
  next?: { batch: number[]; body_total: number; done: number; todo: number }
  A?: RoundLight & { gold: [number, number]; human: [number, number]; errors: Array<{ id: string; pred: string; gold: string }> }
  B?: RoundLight & { review: number; total: number; rate: number; excluded?: number; by_page: Array<{ page: number; n: number }> }
  C?: RoundLight & { total: number; rows: Array<{ slot: number; n: number; pages: number }>; worst?: { slot: number } }
  C2?: RoundLight & { rows: Array<{ page: number; median_gap: number; near_ratio: number }> }
  D?: RoundLight & { rate: number; hit: number; n: number; note?: string; cnn?: boolean }
  E?: RoundLight & { audited: number; hit: number; rate: number; wilson_low: number; form_auto: [number, number]; variant_admits: number; form_open: number; note?: string; errors: Array<{ id: string; pred: string; human: string }> }
  F?: RoundLight & { n_cells: number; n_review: number; rate: number; n_segments: number; n_segments_with_ref: number; by_type?: Record<string, { n_review: number; n_cells: number; rate: number }>; n_lost: number; lost_rate?: number; n_no_ref?: number; lost: Array<{ page: number; col: number; a: number; b: number }> }
}
