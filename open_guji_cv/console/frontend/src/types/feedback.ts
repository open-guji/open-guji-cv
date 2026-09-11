// 对应 GET /api/batches、/api/gold 等，字段照
// v1 static/js/panels/harvest.js 的用法反推（原样复用后端契约）。

export interface Batch {
  id: string
  title: string
  step: string
  kind: string
  transport: string
  url?: string
  n_cards: number
  n_events: number
  n_consumed: number
  status: string
}

export interface GoldShard {
  shard: string
  carrier: string
  n: number
  status?: Record<string, number>
  stratum?: Record<string, number>
}

export interface HarvestResult {
  parsed: number
  appended: number
  total: number
}

export interface RouteResult {
  results: Array<{ consumer: string; added: number; skipped: number; errors: string[] }>
  unrouted?: unknown
}
