// 对应 POST /api/runs 与 GET /api/runs/{job_id}，字段照
// v1 static/js/panels/groups.js::vgResync 与 run.js 的用法反推。

export interface RunRequest {
  book: string
  pipeline: string
  from_step?: string
  to_step?: string
  pages: string
  force?: boolean
  params?: Record<string, unknown>
  allow_sample_db?: boolean
}

export interface RunJob {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  duration?: number
  exit_code?: number
  spec: {
    book: string
    pipeline: string
    from_step?: string | null
    to_step?: string | null
    pages: string
    force?: boolean
    params?: Record<string, unknown>
  }
  [k: string]: unknown
}

export interface LogLineEvent { type: 'line'; line: string }
export interface LogCompleteEvent { type: 'complete'; status: string; exit_code: number; duration: number }
export type LogEvent = LogLineEvent | LogCompleteEvent
