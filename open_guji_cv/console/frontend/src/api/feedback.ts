import { api } from './client'
import type { Batch, GoldShard, HarvestResult, RouteResult } from '../types/feedback'

export const fetchBatches = () => api<Batch[]>('/api/batches')

export function harvestBatch(batchId: string, step: string, kind: string, content: string) {
  return api<HarvestResult>(`/api/batches/${encodeURIComponent(batchId)}/harvest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch: batchId, step, kind, content }),
  })
}

export function routeBatch(batchId: string, dryRun: boolean) {
  return api<RouteResult>(`/api/batches/${encodeURIComponent(batchId)}/route?dry_run=${dryRun}`, { method: 'POST' })
}

export const fetchGoldShards = () => api<{ shards: GoldShard[] }>('/api/gold')

export function migrateGold(shard: string) {
  return api<Record<string, unknown>>(`/api/gold/${encodeURIComponent(shard)}/migrate`, { method: 'POST' })
}

export function driftGold(shard: string) {
  return api<Record<string, unknown>>(`/api/gold/${encodeURIComponent(shard)}/drift`, { method: 'POST' })
}
