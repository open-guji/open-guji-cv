import { api } from './client'
import type { HeadColCardsResponse } from '../types/headRaise'

// 卡片走跟四类边框裁决同一条路由（kind=headcol），回读也走同一个 verdicts
// 端点——后端对 head_raise 事件额外回 raised / n_raised / head_cut 三个字段，
// 不然刷新后「抬高几格」「首字被切」两栏会空着，人会以为没存上而重标一遍。

export function fetchHeadColCards(book: string, pages: string) {
  const qs = `book=${encodeURIComponent(book)}&kind=headcol&pages=${encodeURIComponent(pages)}`
  return api<HeadColCardsResponse>(`/api/border-review/cards?${qs}`)
}

export interface HeadColVerdictRow {
  verdict: string
  raised?: string | null
  n_raised?: number | null
  head_cut?: string | null
}

export function fetchHeadColVerdicts(batch: string) {
  return api<{ batch: string; n: number; verdicts: Record<string, HeadColVerdictRow> }>(
    `/api/border-review/verdicts?batch=${encodeURIComponent(batch)}`)
}
