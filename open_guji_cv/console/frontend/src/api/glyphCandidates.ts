import { api } from './client'
import { postEvents } from './events'

// 字形库「待纳入」（overview#176，2026-09-28）：还没进库的候选刻例，按字分组给人裁收不收。
// 读：console/routers/glyph_candidates.py；清单格式：feedback/candidates.py。
// 写：照常 POST /api/events（kind=admit_candidate）。路由表不给它配消费者——
// 控制台只落事件，进库由 H 道的重放完成。

export type CandVerdict = 'admit' | 'reject' | 'unclear'

export interface CandTally { admit: number; reject: number; unclear: number; todo: number }

export interface CandListInfo {
  id: string; title: string; source?: string | null; n: number; tally: CandTally; n_problems: number
}

export interface CandCell {
  cell_id: string; char: string; book: string; page: number; col: number; slot: number; sub: string
  patch_key: string; evidence: Record<string, unknown>; ref_instances: string[]
  decision: { v: CandVerdict; char?: string; ts?: string; reviewer?: string | null } | null
}

export interface CandLibExemplar { instance_id: string; provenance: string; edition?: string; is_ref: boolean }

export interface CandGroup { char: string; cells: CandCell[]; n_lib: number | null; lib: CandLibExemplar[] }

export interface CandList {
  id: string; meta: Record<string, unknown>; problems: string[]; batch: string; kind: string; step: string
  verdicts: CandVerdict[]; tally: CandTally; groups: CandGroup[]
}

export const fetchCandLists = () => api<{ dir: string; lists: CandListInfo[] }>('/api/glyphlib/candidates')
export const fetchCandList = (id: string, lib = 8) =>
  api<CandList>(`/api/glyphlib/candidates/${encodeURIComponent(id)}?lib=${lib}`)

/** 候选格字块图的地址（不带 query；交给 BinaryToggleImage 包 ws 与 src=bin）。 */
export const candPatchSrc = (c: CandCell) =>
  `/api/cache/${encodeURIComponent(c.book)}/char_patch/${encodeURIComponent(c.patch_key)}.png`  // ws-ok: BinaryToggleImage 内部 withWorkspace

/** 落一条裁决。payload 带 shape：H 道重放可按 confirm 同一口径（glyphdb_admit）送进库。 */
export function postCandDecision(list: CandList, cell: CandCell, v: CandVerdict) {
  return postEvents({
    batch: list.batch, step: list.step, unit: 'cell', kind: list.kind, consume: false,
    events: [{
      id: cell.cell_id, t: Date.now(), v, char: cell.char, shape: cell.char,
      list: list.id, evidence: cell.evidence,
    }],
  })
}
