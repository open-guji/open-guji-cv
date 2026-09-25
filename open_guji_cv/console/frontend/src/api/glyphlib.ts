import { api, withWorkspace } from './client'

// 字形库总览，见 console/routers/glyphlib.py 与 overview 仓
// 项目进展/图片初步数字化/进度/字形库/02-控制台字形库总览.md。
// 口径全在 clustering/glyph_ledger.py：一个 glyph.db 的全部非字体来源 = 本书套。

export type Prov = Record<string, number>

export interface LibEdition { edition: string; kind: 'font' | 'woodblock'; chars: number; stable: number; exemplars: number }

export interface LibSummary {
  db: string
  sources: { source_id: string; edition_tag: string; kind: string; title: string | null; pipeline_version: string | null }[]
  editions: LibEdition[]
  book: {
    chars: number; exemplars: number; cells: number; shadow_duplicates: number
    provenance: Prov; human_share: number; chars_with_human: number
    singleton_chars: number; chars_split_across_editions: number
  }
  fonts: Record<string, { chars: number; book_chars_not_in_font: number }>
  store: { db_exemplars: number; store_exemplars: number | null; ok: boolean; message: string | null }
  head_anomalies: number
  others: { ws: string; name: string; chars?: number; common?: number; error?: string }[]
}

export interface LibChar {
  char: string; cp: number | null; n: number; prov: Prov; semantic: string
  editions: string[]; in_font: boolean | null; also_in: string[]
}

export interface LibExemplar {
  instance_id: string; cell: string; edition: string; provenance: string; provenance_raw: string | null
  semantic: string | null; page: string; col: number; idx: number; duplicate: boolean
  admitted_at: string | null; event: string | null
}

export interface LibCharDetail {
  char: string; cp: number | null
  heads: { edition: string; semantic: string | null; unicode_cp: number | null; status: string; n_confirmed: number }[]
  exemplars: LibExemplar[]
  fonts: { edition: string; instance_id: string }[]
  others: { ws: string; name: string; n: number; exemplars: LibExemplar[] }[]
}

export const fetchLibSummary = () => api<LibSummary>('/api/glyphlib/summary')
export const fetchLibChars = () => api<{ chars: LibChar[] }>('/api/glyphlib/chars')
export const fetchLibChar = (c: string) => api<LibCharDetail>(`/api/glyphlib/char/${encodeURIComponent(c)}`)

/** 刻例图块。`ws` 给了就取那个工作区的库（跨书并排），否则本页工作区。 */
export function libPatchUrl(instanceId: string, ws?: string) {
  const u = `/api/glyphlib/patch/${encodeURIComponent(instanceId)}.png`
  return ws ? `${u}?ws=${encodeURIComponent(ws)}` : withWorkspace(u)
}

/** 来路的中文名与顺序：人裁在前（新 Step7 的铁证来源），机器通道在后。 */
export const PROV_LABEL: Record<string, string> = {
  human: '人裁', align: '整理本对齐', match: '库匹配', context: '上下文', render: '字体', unknown: '未知',
}
export const PROV_ORDER = ['human', 'align', 'match', 'context', 'unknown']

export const libFontUrl = (c: string) => withWorkspace(`/api/glyphlib/font/${encodeURIComponent(c)}.png`)

// ── 体检（字形库 03）──
export interface AuditFinding {
  instance_id: string; char: string; provenance: string; flags: string[]; score: number; key: string
  n_same_self: number; best_same: number; best_same_self: number; same_peer: string | null; same_peer_ws: string
  rival: number; rival_char: string | null; rival_peer: string | null; rival_prov: string | null
  xrival: number; xrival_char: string | null; xrival_peer: string | null; xrival_ws: string
  font_own: number | null; font_best: number; font_char: string | null
  human_conflict: boolean
  decision?: { v: string; char?: string; target?: string } | null
}
export interface AuditResult {
  meta: { n_checked?: number; n_flagged?: number; flag_counts?: Record<string, number>; created_at?: string
    others?: string[]; params?: Record<string, number>; seconds?: number }
  flag_labels: Record<string, string>; out: string
  n_total: number; n_decided: number; findings: AuditFinding[]
}
export const fetchLibAudit = (all = false) => api<AuditResult>(`/api/glyphlib/audit${all ? '?all=1' : ''}`)

export interface AuditDecision {
  key: string; instance_id: string; v: 'ok' | 'near_form' | 'evict' | 'relabel'
  target?: string; char?: string; char_self?: string; peer?: string | null; peer_char?: string | null; flags?: string[]
}
export const postLibAudit = (d: AuditDecision) =>
  api<{ ok: boolean; error?: string; consume_error?: string }>('/api/glyphlib/audit/decide', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d),
  })
