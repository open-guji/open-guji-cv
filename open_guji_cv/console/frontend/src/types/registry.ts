// 对应后端 core/book.py::Book.to_dict / core/pipeline.py::Pipeline.to_dict /
// core/step.py::Step.describe。字段只列前端用得到的，其余用 [k: string]: unknown 兜底
// ——后端加字段不用同步改这里，减字段才会报错（更安全的方向）。

export interface PrecleanRule {
  kind: string
  note?: string
  [k: string]: unknown
}

export interface Book {
  id: string
  title: string
  n_pages: number
  /** 'keben'（刻本，默认）| 'modern'（现代排印本）——决定 Step1–3 的后端 step id。 */
  edition?: string
  /** 这册书默认走的管线 id（后端 core/book.py::default_pipeline_id）。 */
  pipeline?: string
  dev_set: number[]
  sets: Record<string, number[]>
  notes: string
  preclean_pages: number[]
  preclean: Record<string, PrecleanRule[]>
  [k: string]: unknown
}

export interface StepDescribe {
  id: string
  title: string
  version: string
  unit: string
  consumes: string[]
  produces: string[]
  when?: string
  [k: string]: unknown
}

export interface Pipeline {
  id: string
  title: string
  selector: string
  steps: StepDescribe[]
  edges: Array<{ from: string; to: string; kind: string }>
  notes: string
  [k: string]: unknown
}
