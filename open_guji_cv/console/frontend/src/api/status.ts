import { api } from './client'
import type { StatusResponse } from '../types/status'

export function fetchStatus(book: string, pipeline: string, pages = 'dev_set') {
  const qs = `book=${encodeURIComponent(book)}&pipeline=${encodeURIComponent(pipeline)}&pages=${encodeURIComponent(pages)}`
  return api<StatusResponse>(`/api/status?${qs}`)
}
