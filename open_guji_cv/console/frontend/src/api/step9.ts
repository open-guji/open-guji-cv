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

// 9.0 进度复查（看板，不是闸——有待办也允许跑 9.1/9.2）。口径见 report/progress.py。
export interface Step9ProgressRow {
  page: number
  stale: number
  stale_steps: string[]
  review_new: number       // Step7 待人裁：未放行 ∧ 未裁过 —— 与裁决台出卡数逐 id 相等
  review_decided: number   // 已裁未放行：人裁过了、机器没采信，不是待办
  cut: number
  defect: number
  excluded: number
  cols_bad: number
}

export interface Step9ProgressResponse {
  book: string
  pages: Step9ProgressRow[]
  totals: Record<string, number>
  n_pages: number
  n_clean: number
}

export function fetchStep9Progress(book: string, pages: string) {
  const qs = `pages=${encodeURIComponent(pages)}`
  return api<Step9ProgressResponse>(`/api/step9/progress/${encodeURIComponent(book)}?${qs}`)
}
