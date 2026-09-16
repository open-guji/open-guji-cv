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
  /** 原图在不在当前 GUJI_WORKSPACE 下。false = 换个工作区才看得到它的数据。 */
  in_workspace?: boolean
  /** 'ruled'（有版框界行，默认）| 'none'（无版框）。界行类裁决台据此显隐。 */
  frame?: string
  /** 'vertical-rl'（竖排，默认）| 'horizontal-tb'（横排，尚未实现）。 */
  writing_mode?: string
  /** 'trad' | 'simp'。 */
  script?: string
  /** 是否启用 Step5-c OCR 候选。 */
  ocr_candidates?: boolean
  /** 登记的整理本数量；0 = Step5-d 锚定没有意义。 */
  n_references?: number
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
