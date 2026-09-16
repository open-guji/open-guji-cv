import { api } from './client'
import type { StatusResponse } from '../types/status'

export function fetchStatus(book: string, pipeline: string, pages = 'dev_set') {
  const qs = `book=${encodeURIComponent(book)}&pipeline=${encodeURIComponent(pipeline)}&pages=${encodeURIComponent(pages)}`
  return api<StatusResponse>(`/api/status?${qs}`)
}

/** 写回本书 book yaml 的 `ocr_candidates:` 字段（Step5-c OCR候选开关）。 */
export function setOcrCandidates(book: string, enabled: boolean) {
  return api<{ book: string; ocr_candidates: boolean }>(
    `/api/books/${encodeURIComponent(book)}/ocr_candidates`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) },
  )
}
