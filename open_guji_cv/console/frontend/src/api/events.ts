import { api } from './client'
import type { ConsumeResult } from '../domain'

export interface EventsInBody {
  batch: string
  step: string
  unit?: string
  kind?: string
  events: Array<Record<string, unknown>>
  consume?: boolean
}

export interface EventsOut extends ConsumeResult {
  appended: number
  batch: string
  total: number
  unrouted?: unknown
}

export function postEvents(body: EventsInBody) {
  return api<EventsOut>('/api/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
