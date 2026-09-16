import { api } from './client'

export interface LlmOnlineWrongExample {
  id: string
  llm_said: string | null
  human_final: string
  candidates: string[] | null
}

export interface LlmOnlineStats {
  has_data: boolean
  n_total_calls: number
  n_answered_in_candidates?: number
  n_resolved?: number
  n_correct?: number
  n_wrong?: number
  accuracy?: number | null
  by_model?: Record<string, { n: number; correct: number; accuracy: number }>
  wrong_examples?: LlmOnlineWrongExample[]
}

export const fetchLlmOnlineStats = (book: string) =>
  api<LlmOnlineStats>(`/api/llm_online_stats?book=${encodeURIComponent(book)}`)

// 单条线上调用日志——字段照抄 `context_decide.py::_ask_llm_online` 里
// `_log_llm_call` 写的 dict，原样透出，不改名不裁字段。
export interface LlmOnlineCall {
  ts: string
  id: string
  book: string
  page: number
  candidates_chars: string[]
  context_before: string
  context_after: string
  provider: string
  model: string
  llm_raw_text: string
  llm_parsed_char: string | null
  llm_parse_ok: boolean
  llm_answer_in_candidates: boolean
  cached: boolean
  latency_s: number
  prompt_tokens: number | null
  completion_tokens: number | null
  error: string | null
  wall_time_s: number
}

export interface LlmOnlineCallsResponse {
  book: string
  page: number | null
  total: number
  rows: LlmOnlineCall[]
}

export const fetchLlmOnlineCalls = (book: string, page?: number, limit = 200) => {
  const qs = new URLSearchParams({ limit: String(limit) })
  if (page) qs.set('page', String(page))
  return api<LlmOnlineCallsResponse>(`/api/llm_online_calls/${encodeURIComponent(book)}?${qs}`)
}
