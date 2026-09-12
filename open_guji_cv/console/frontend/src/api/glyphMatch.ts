import { api } from './client'

// Step5-a 字形库匹配调试视图，见 console/routers/glyph_match.py 与 overview
// 仓 项目进展/图片初步数字化/进度/Step5-字符识别/08-5a方案-字形库匹配调试视图.md。

export interface GlyphMatchCandidate {
  char: string
  cov: number
}

export interface GlyphMatchResult {
  id: string
  verdict: 'same' | 'unsure' | 'diff'
  char: string | null
  matched_id: string | null
  cov: number
  wmax: number
  guard: string | null
  n_verified: number
  candidates: GlyphMatchCandidate[]
}

export function fetchGlyphMatch(book: string, page: number, col: number, slot: number, sub?: string, k = 10) {
  const q = `?k=${k}` + (sub ? `&sub=${encodeURIComponent(sub)}` : '')
  return api<GlyphMatchResult>(`/api/glyph-match/${encodeURIComponent(book)}/${page}/${col}/${slot}${q}`)
}

// exemplar 缩略图——same 档候选第一名才有（见 GlyphMatchResult.matched_id），
// 其余候选字没有唯一对应的具体刻例，不配图（见后端路由 docstring）。
export function glyphMatchExemplarUrl(instanceId: string) {
  return `/api/glyph-match/exemplar/${encodeURIComponent(instanceId)}.png`
}

export interface GlyphMatchSummary {
  n_pages: number
  n_missing: number
  verdict_counts: { same: number; unsure: number; diff: number }
  guard_counts: Record<string, number>
}

export function fetchGlyphMatchSummary(book: string, pages?: string) {
  const q = pages ? `?pages=${encodeURIComponent(pages)}` : ''
  return api<GlyphMatchSummary>(`/api/glyph-match/${encodeURIComponent(book)}/summary${q}`)
}
