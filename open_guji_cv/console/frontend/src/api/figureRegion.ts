import { api, withWorkspace } from './client'

/** 插图块画框（`console/routers/figure_region.py`，GUJI-737，2026-10-24）。坐标一律 canvas 像素（左上原点）。 */
export interface FigureRegion {
  box: [number, number, number, number]
  col?: number
  span?: number
  alt: string
  fig?: string
}

export interface FigureColumn {
  col: number
  x: number
  w: number
}

export interface FigurePage {
  book: string
  page: number
  width: number
  height: number
  columns: FigureColumn[]
  regions: FigureRegion[]
}

export function fetchFigurePages(book: string) {
  return api<{ book: string; pages: Record<string, FigureRegion[]> }>(
    `/api/figure-region/${encodeURIComponent(book)}`)
}

export function fetchFigurePage(book: string, page: number) {
  return api<FigurePage>(`/api/figure-region/${encodeURIComponent(book)}/${page}`)
}

/** 整页覆盖；`regions: []` 撤掉本页全部插图块。没填列号的由后端按框算。 */
export function saveFigurePage(book: string, page: number, regions: FigureRegion[]) {
  return api<{ appended: number; regions: FigureRegion[] }>(
    `/api/figure-region/${encodeURIComponent(book)}/${page}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ regions }),
    })
}

export function rawPageUrl(book: string, page: number, scale: number) {
  return withWorkspace(`/api/raw/${encodeURIComponent(book)}/${page}.png?scale=${scale.toFixed(3)}`)
}
