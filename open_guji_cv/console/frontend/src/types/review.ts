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

/** 词典严格异体分组（方案-词典加AI接入管线 §三 `groups`）：组内是同一个字的不同写法。 */
export interface AiGroup {
  id: string
  members: string[]
  why: string
}

export interface AiDropReason {
  c: string
  why: string
}

export interface AiRankItem {
  group: string   // 对应 AiGroup.id
  p: number
  why: string
}

/**
 * Step6 AI 判断层证据（方案 §三）。只对「问过 AI」的格有——图像两路不一致
 * 或缺一路的格，北行约 11%。没有这个字段（`card.ai` 缺失）的书（四庫等）
 * 卡片按老逐像素行为走，不显示 AI 部分。
 */
export interface AiEvidence {
  runs: number
  drop: string[]
  drop_why: AiDropReason[]
  rank: AiRankItem[]
  confidence: string        // 高 | 中 | 低
  need_human: string
  conflict_with_img: boolean   // AI 首组不含图像共识 → 标「疑似刻本讹字/整理本改字」
  /** 各次运行首组的代表字；两次不一致时标「AI 拿不准」，列出这里的两个字
   * （2026-09-27 C 道暂拟字段，方案原稿未定，见 done 单）。 */
  runs_top: string[]
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
  /** Step6-AI 三层证据：词典分组（`groups`）与 AI 排序/排除/把握度（`ai`）。
   * 两者都缺失 = 这一格没接 Step6-AI（四庫等书恒缺）。 */
  groups?: AiGroup[] | null
  ai?: AiEvidence | null
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
