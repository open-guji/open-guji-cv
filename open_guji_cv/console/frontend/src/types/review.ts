// 对应 GET /api/review/cards 等，字段照 v1 static/js/panels/review.js 用法反推
// （原样复用后端契约，见方案 §一）。

export interface ReviewCardRef {
  char?: string
  op?: string
  form?: string
}

export interface ReviewCardDb {
  verdict: string
  cov: number
  candidates?: Array<[string, number]>
}

export interface ReviewCardCtx {
  char?: string
  margin?: number
  source?: string
  llm_suggestion?: string | null
}

export interface ReviewCardForm {
  state: 'open' | string
  semantic: string
  forms: string[]
  human?: Record<string, number>
  lib?: Array<[string, number]>
}

export interface ReviewCard {
  id: string
  page: number
  col: number
  slot: number
  sub?: string
  channel?: string
  patch: string
  ref?: ReviewCardRef
  db?: ReviewCardDb
  ctx?: ReviewCardCtx
  /** 己/已/巳：按上下文定的建议字与依据（utils/ji_yi_si.py） */
  jys?: { char: string | null; why: string } | null
  ocr?: Array<[string, number]>
  doubts?: string[]
  form?: ReviewCardForm
}

export interface ReviewCardsResponse {
  cards: ReviewCard[]
  blocked?: unknown[]
  /** 全书所有批次已裁过的字位数（后端跨批次去重）。skip_decided 开时这些卡已被跳过。 */
  n_decided?: number
}

export interface ReviewVerdict {
  shape: string
  done: string
  ts?: number
  dwell?: number
  noGlyphLib?: boolean
}

export interface ReviewVerdictsResponse {
  verdicts: Record<string, ReviewVerdict>
}

export interface RareCandidate {
  char: string
  score: number
  py?: string
  font?: string
  ids?: string
  cp?: string
  std?: string
  std_freq?: number
  freq?: number
  gloss?: string
  zi: string
  /** 结构解释（ids_struct 口径）：{top: '⿰', slots: {L: '言', R: '俞'}}；独体 top='独体' */
  struct?: { top: string; slots: Record<string, string> }
  near?: { char: string; kind: string; cos: number; detail: string }[]
  gw?: { name: string; source: string; cos: number; url: string }
}

export interface AroundSlot {
  char?: string
  review?: boolean
  source?: string
}

export interface AroundContext {
  slots: AroundSlot[]
  at: number
}
