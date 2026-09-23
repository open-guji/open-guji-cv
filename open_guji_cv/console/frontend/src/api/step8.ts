import { api } from './client'

// Step8 对勘与复核。设计见 overview 仓 Step8-落库反馈/04、05 两篇。
// 两个接口都**读已有产物、不现跑**：对勘一次 ~100s，不能每次开页面都跑。

export type Step8Tier = 'taboo' | 'variant' | 'jiajie' | 'book' | 'dispute'

export interface Step8Sample {
  id: string; page: number; col: number; slot: number; sub: string | null
  hyp_ctx: string; ref_ctx: string; channel: string | null; human: boolean; kind: string
}

export interface Step8Pair {
  pair: [string, string]      // [刻本形, 校对本形]
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

// 一次复核裁决。**按字对提交**：`ids` 是这次要裁的字位
// （「N 处一起裁」勾上 = 全部，不勾 = 只当前这一处）。
export interface Step8Decide {
  book: string; pair: [string, string]; ids: string[]
  who?: string        // ours | theirs | neither（③ 第一级）
  rel?: string        // jiajie | diff（③ 第二级）
  kind?: string       // ② 的性质：人名/物品/通假/异体/避諱/正俗；① 的 不是异体
  fix?: string        // who=neither 时人输入的正确字
  note?: string
}

export function postStep8Decide(d: Step8Decide) {
  return api<{ ok: boolean; error?: string; appended?: number; kinds?: string[]
    consumed?: { consumer: string; added: number; skipped: number; errors: string[] }[]
    consume_error?: string }>('/api/step8/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(d),
    })
}
