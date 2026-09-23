import { api } from './client'

// Step8 对勘与复核。设计见 overview 仓 Step8-落库反馈/04、05 两篇。
// 两个接口都**读已有产物、不现跑**：对勘一次 ~100s，不能每次开页面都跑。

export type Step8Tier = 'taboo' | 'common' | 'book' | 'dispute'

export interface Step8Sample {
  id: string; page: number; col: number; slot: number; sub: string | null
  hyp_ctx: string; ref_ctx: string; channel: string | null; human: boolean; kind: string
}

export interface Step8Pair {
  pair: [string, string]      // [刻本形, 证人形]
  tier: Step8Tier
  n: number                   // 全书出现几处
  ids: string[]
  pages: number[]
  samples: Step8Sample[]      // 前 3 个实例，出图与上下文用
  decided: boolean
}

export interface Step8AbsentRun {
  page: number; col: number; n: number; kind: string; text: string; witness: string
}

export interface Step8Overview {
  book: string
  has_report: boolean
  hint?: string
  file?: string
  built_at?: string
  pages?: number[]
  n_slots?: number
  n_equal?: number
  tiers?: Record<Step8Tier, { pairs: number; items: number }>
  tier_label?: Record<Step8Tier, string>
  n_decided?: number
  absent_runs?: Step8AbsentRun[]
  gaps?: number
}

export function fetchStep8Overview(book: string) {
  return api<Step8Overview>(`/api/step8/overview/${encodeURIComponent(book)}`)
}

// `undecided` 只看没复核过的；`tier` 空 = 全部层。
export function fetchStep8Pairs(book: string, tier = '', undecided = true, limit = 200) {
  const qs = `tier=${encodeURIComponent(tier)}&undecided=${undecided}&limit=${limit}`
  return api<{ pairs: Step8Pair[]; total: number; has_report: boolean; truncated: boolean }>(
    `/api/step8/pairs/${encodeURIComponent(book)}?${qs}`)
}
