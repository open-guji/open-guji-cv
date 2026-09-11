import { api } from './client'
import type { RunJob, RunRequest } from '../types/runs'

export function submitRun(req: RunRequest) {
  return api<RunJob>('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
}

export function fetchRun(jobId: string) {
  return api<RunJob>(`/api/runs/${encodeURIComponent(jobId)}`)
}

export function fetchRuns(limit = 30) {
  return api<RunJob[]>(`/api/runs?limit=${limit}`)
}

export function cancelRun(jobId: string) {
  return api<void>(`/api/runs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' })
}
