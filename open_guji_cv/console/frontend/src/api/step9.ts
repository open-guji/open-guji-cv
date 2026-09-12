import { api } from './client'

// 见 console/routers/step9.py::api_step9_render。现场渲染，不进管线、不落盘——
// pages 支持 book.resolve_pages 认得的表达式（单页/逗号/区间）。
export interface Step9RenderResponse {
  text: string
  pages: number[]
  stale: string[]
}

export function fetchStep9Render(book: string, pages: string) {
  const qs = `pages=${encodeURIComponent(pages)}`
  return api<Step9RenderResponse>(`/api/step9/render/${encodeURIComponent(book)}?${qs}`)
}
