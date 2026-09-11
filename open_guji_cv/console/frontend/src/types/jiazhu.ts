// 对应 GET /api/jiazhu/segments，字段照 v1 static/js/panels/jiazhu.js 的用法反推
// （原样复用后端契约，见方案 §一）。

export interface JiazhuCell {
  id: string
  char?: string
  ref?: string
  admit?: boolean
  channel?: string
  patch: string
}

export interface JiazhuSegment {
  id: string
  n: number
  n_review: number
  a: unknown[]
  b: unknown[]
  cells: JiazhuCell[]
  img: string
  ref?: string
  text: string
}

export interface JiazhuSegmentsResponse {
  pages: number[]
  n: number
  n_review: number
  segments: JiazhuSegment[]
}
