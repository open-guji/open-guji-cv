import { api, withWorkspace } from './client'
import { postEvents } from './events'

// 格级审阅（GUJI-364b，2026-10）：单字特写逐格裁「是哪个字」。
// 读：console/routers/cell_review.py（清单、候选、已落裁决；TSV 导出）。
// 写：照常 POST /api/events（kind=cell_review，批次 cellreview-<清单 id>），consume=false——
// 路由表不给它配消费者，这里只落事件，不写定字、不进字形库。
// 校验与后端 feedback/cell_review.py 的 check_payload 同口径（前端先挡，后端兜底）。

export type CellVerdict = 'pick' | 'none' | 'unsure' | 'other'

export interface CellDecision {
  verdict: CellVerdict; picked: string | null; other_char: string | null; note: string
  reviewer: string | null; ts: string; client_ts: number | null
}

export interface CellReviewCell {
  cell_id: string; char: string; cands: string[]; reason?: string
  book: string; page: number; col: number; slot: number; sub: string; patch_key: string
  decision: CellDecision | null
}

export interface CellReviewView {
  id: string; meta: Record<string, unknown>; problems: string[]; batch: string; kind: string; step: string
  verdicts: CellVerdict[]; tally: Record<CellVerdict | 'todo', number>; cells: CellReviewCell[]
}

export const fetchCellReview = (id: string) =>
  api<CellReviewView>(`/api/cell-review/${encodeURIComponent(id)}`)

/** TSV 导出地址（带工作区查询串，`<a href download>` 直接用）。 */
export const cellReviewTsvHref = (id: string) =>
  withWorkspace(`/api/cell-review/${encodeURIComponent(id)}.tsv`)

/** 字块图地址（不带 query；交给 BinaryToggleImage 包 ws 与 src=bin）。 */
export const cellPatchSrc = (c: CellReviewCell) =>
  `/api/cache/${encodeURIComponent(c.book)}/char_patch/${encodeURIComponent(c.patch_key)}.png`  // ws-ok: BinaryToggleImage 内部 withWorkspace

export interface CellChoice { verdict: CellVerdict; picked?: string; other_char?: string; note?: string }

/** 落一条裁决。`client_ts` 由前端填（服务端会剥掉 `t`，见 feedback/cell_review.py 说明）。 */
export function postCellDecision(view: CellReviewView, cell: CellReviewCell, c: CellChoice) {
  return postEvents({
    batch: view.batch, step: view.step, unit: 'cell', kind: view.kind, consume: false,
    events: [{
      id: cell.cell_id, verdict: c.verdict,
      picked: c.verdict === 'pick' ? c.picked ?? null : null,
      other_char: c.verdict === 'other' ? c.other_char ?? null : null,
      note: c.note ?? '', client_ts: Date.now(),
    }],
  })
}
