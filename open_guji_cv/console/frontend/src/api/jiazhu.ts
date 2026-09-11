import { api } from './client'
import type { JiazhuSegmentsResponse } from '../types/jiazhu'

export function fetchJiazhuSegments(book: string, pages: string, only: string, batch: string) {
  const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`
    + `&only=${encodeURIComponent(only)}&batch=${encodeURIComponent(batch)}`
  return api<JiazhuSegmentsResponse>(`/api/jiazhu/segments?${qs}`)
}
