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
