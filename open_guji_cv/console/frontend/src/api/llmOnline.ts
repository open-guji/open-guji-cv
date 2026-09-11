import { api } from './client'

export interface LlmOnlineStats {
  has_data: boolean
  n_total_calls: number
  n_resolved?: number
  accuracy?: number | null
}

export const fetchLlmOnlineStats = (book: string) =>
  api<LlmOnlineStats>(`/api/llm_online_stats?book=${encodeURIComponent(book)}`)
