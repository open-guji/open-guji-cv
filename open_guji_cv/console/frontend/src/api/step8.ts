import { api } from './client'

// Step8 对勘与复核。设计见 overview 仓 Step8-落库反馈/04、05 两篇。
// 两个接口都**读已有产物、不现跑**：对勘一次 ~100s，不能每次开页面都跑。

export type Step8Tier = 'taboo' | 'variant' | 'jiajie' | 'book' | 'dispute'

export interface Step8Sample {
  id: string; page: number; col: number; slot: number; sub: string | null
  hyp_ctx: string; ref_ctx: string
  seg?: Step8Seg[]            // 人标过的切分缺陷（跨批次，Step7 标的也算）
}

// 切分反馈：字形不完整 / 有噪声。与「谁对 / 哪一类」独立，只留作 Step3 的反馈。
export type Step8Seg = 'truncated' | 'contaminated'

// 每处各自的勾选状态；「N 处一起裁」时一次提交 N 处
export function postStep8Seg(book: string, items: { id: string; flags: Step8Seg[] }[]) {
  return api<{ ok: boolean; error?: string; appended?: number; consume_error?: string }>(
    '/api/step8/seg', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ book, items }),
    })
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

// ── 复核队列（2026-09-24 改两层分类）─────────────────────────────
// 第一层 待审 / 我方对 / 校对本对 / 都不对；第二层只挂在「我方对」下：异体/通假/避讳/其他。
// 自动档（避諱表 / 关系图 / 通假表）没人裁时直接放进「我方对」对应小类，`basis='auto'`。
export type Step8Bucket = 'pending' | 'ours' | 'theirs' | 'neither'
export type Step8Cat = 'variant' | 'jiajie' | 'taboo' | 'other'

export interface Step8Group {
  pair: [string, string]
  who: Step8Bucket
  cat: Step8Cat | null
  fix: string
  basis: '' | 'human' | 'auto' | 'convention'
  tier: Step8Tier              // 自动判据的档，只作预标注
  default_cat: Step8Cat        // 待审卡默认选中的小类
  final: string                // 这几处最终落的字
  n: number
  ids: string[]
  pages: number[]
  samples: Step8Sample[]       // 全部字位，按页列排好
  decided_at: string
}

export interface Step8Count { pairs: number; items: number; auto: number }

export interface Step8Queue {
  book: string
  has_report: boolean
  counts: Record<Step8Bucket, Step8Count> & { cats: Record<Step8Cat, Step8Count> }
  groups: Step8Group[]
  total: number
  truncated: boolean
}

// `cat` 只在 bucket=ours 时有意义，空 = 我方对全部
export function fetchStep8Queue(book: string, bucket: Step8Bucket, cat = '', limit = 500) {
  const qs = `bucket=${bucket}&cat=${encodeURIComponent(cat)}&limit=${limit}`
  return api<Step8Queue>(`/api/step8/queue/${encodeURIComponent(book)}?${qs}`)
}

// 一次复核裁决 = 把 `ids` 这几处**挪进**某一类。`who` 空 = 退回待审。
// 「N 处一起裁」勾上 = 全部，不勾 = 只当前这一处。
export interface Step8Decide {
  book: string; pair: [string, string]; ids: string[]
  who: Step8Bucket | ''
  cat?: Step8Cat      // who=ours 时的小类
  fix?: string        // who=neither 时人输入的正确字
  note?: string
}

export function postStep8Decide(d: Step8Decide) {
  return api<{ ok: boolean; error?: string; appended?: number; kinds?: string[]
    changed?: number; final?: string
    consumed?: { consumer: string; added: number; skipped: number; errors: string[] }[]
    consume_error?: string }>('/api/step8/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(d),
    })
}
