// 对应 GET /api/cutline/cases 与 /api/cutline/verdicts，字段照
// v1 static/js/panels/cutline.js 的用法反推（原样复用后端契约，见方案 §一）。

export interface CandidateMatch {
  verdict: 'same' | 'unsure' | 'diff' | string
  char: string | null
  cov: number
  wmax: number
  // unsure 档没有单一 char 时的候选池（字, cov），降序，最多 3 个
  // （overview 2026-09-11 下发：char 为 null 不该只显示问号）
  candidates?: Array<[string, number]>
}

export interface CutCandidate {
  kind: 'straight' | 'seam_narrow' | 'seam_wide' | string
  y: number[] | null
  seam_ink: number
  dev_max: number
  /** U-Net 裁判的置信加权一致率 [0,1]；没过裁判为空（2026-09-14） */
  agree?: number | null
  /** 与 U-Net 归属分歧的最大连通块 px（L2′ 升级门槛看它；2026-09-15） */
  dis_unet?: number | null
  // 选这个切法，上格/下格库匹配认出的字（overview 2026-09-11 下发）。
  // null = 没跑过 Step4/5 或没有匹配结果，前端按"无识别信息"处理。
  match_above?: CandidateMatch | null
  match_below?: CandidateMatch | null
}

export interface CutlineCase {
  /** drift 档（坐标过期重标）：kind === 'drift'；redo = 本批次已对当前坐标系裁过（只看未裁取消时才出） */
  kind?: string
  redo?: boolean
  drift_from_col_h?: number | null
  id: string
  page: number
  col: number
  bi: number
  ink: number
  y: number
  y0: number
  y1: number
  x0: number
  x1: number
  col_w?: number
  col_h: number
  crop_y0: number
  crop_y1: number
  img: string
  seam?: number[] | null
  candidates: CutCandidate[]
  chosen: number | null
  slot_above: number
  slot_below: number
  // 「整理本期望」= 整理本给的文意读法（v2_align 的 `reading`）。
  char_above?: string
  char_below?: string
  // v2 定字认的刻本形（`shape`）。与 reading 不同即一次转换，conv_* 为 true；
  // 此前卡片把 shape 当成「整理本期望」显示，两层混为一谈（2026-09-13 修）。
  shape_above?: string
  shape_below?: string
  conv_above?: boolean
  conv_below?: boolean
}

export interface CutlineCasesResponse {
  book: string
  pages: number[]
  n_r2s: number
  n_done: number
  n: number
  // 本批里真拿到「整理本期望」两字的条数——锚定失败时是 0，但页面照常渲染，
  // 所以要显式报出来（2026-09-12）。
  n_expect?: number
  // 语料读成仓内小样本时的警告文案；null = 正常。
  warn?: string | null
  cases: CutlineCase[]
}

export interface CutlineVerdict {
  verdict: string
  y?: number
  polyline?: Array<[number, number]>
  cand?: string
  /** 裁决时的列图高，drift 档据此判断是否对当前坐标系裁的 */
  col_h?: number
}

export interface CutlineVerdictsResponse {
  verdicts: Record<string, CutlineVerdict>
}
