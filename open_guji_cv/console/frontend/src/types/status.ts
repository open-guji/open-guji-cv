// 对应 GET /api/status，字段照 v1 static/js/panels/overview.js 的用法反推
// （原样复用后端契约，见方案 §一：v2 不改路由签名）。

export interface StatusCell {
  status: 'fresh' | 'stale' | 'missing' | 'failed' | 'blocked'
  elapsed?: number | null
  error?: string | null
}

export interface StepStatus {
  counts: { fresh: number; stale: number; missing: number; failed: number; blocked: number }
  pages: Record<string, StatusCell>
}

export interface StatusResponse {
  pages: (string | number)[]
  all_pages?: (string | number)[]
  steps: Record<string, StepStatus>
  workspace?: { workspace: string; is_sample_db: boolean }
  running?: { id: string } | null
}
