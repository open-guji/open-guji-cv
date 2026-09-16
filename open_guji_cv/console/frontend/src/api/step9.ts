import { api } from './client'

// 见 console/routers/step9.py。现场渲染，不进管线、不落盘——
// pages 支持 book.resolve_pages 认得的表达式（单页/逗号/区间）。

// 9.1 坐标转字符位
export interface Step9RenderResponse {
  text: string
  pages: number[]
  stale: string[]
}

export function fetchStep9Render(book: string, pages: string) {
  const qs = `pages=${encodeURIComponent(pages)}`
  return api<Step9RenderResponse>(`/api/step9/render/${encodeURIComponent(book)}?${qs}`)
}

// 9.2 可阅读排版
export interface Step9Paragraph {
  text: string
  is_title: boolean
}

export interface Step9ReflowPage {
  page: number
  paragraphs: Step9Paragraph[]
  notes: string[]
}

export interface Step9ReflowResponse {
  pages: Step9ReflowPage[]
  stale: string[]
}

export function fetchStep9Reflow(book: string, pages: string, baselineKg: number) {
  const qs = `pages=${encodeURIComponent(pages)}&baseline_kg=${baselineKg}`
  return api<Step9ReflowResponse>(`/api/step9/reflow/${encodeURIComponent(book)}?${qs}`)
}
