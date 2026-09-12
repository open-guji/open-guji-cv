import { api } from './client'

export interface CellShrinkRandRow {
  id: string
  book: string
  page: number
  col: number
  patch_key: string
  bbox_page: [number, number, number, number]
  stratum: string
  seed_tag: string
}

export interface CellShrinkRandSample {
  n_pool: number
  n: number
  seed: number
  rows: CellShrinkRandRow[]
}

export function fetchCellShrinkRandSample(n = 400, seed = 20260911, tag = 'r1') {
  return api<CellShrinkRandSample>(`/api/cell-shrink-rand/sample?n=${n}&seed=${seed}&tag=${encodeURIComponent(tag)}`)
}

export function cellShrinkRandContextUrl(book: string, page: number, col: number, slot: number) {
  return `/api/cell-shrink-rand/context/${encodeURIComponent(book)}/${page}/${col}/${slot}.png`
}

export function cellShrinkPatchUrl(book: string, patchKey: string) {
  return `/api/cache/${encodeURIComponent(book)}/char_patch/${encodeURIComponent(patchKey)}.png`
}
