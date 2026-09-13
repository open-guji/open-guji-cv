// 对应 GET /api/border-review/cards?kind=headcol 与 /api/border-review/verdicts。
//
// 列级抬头精标（overview `Step3-逐字切分/03-抬头综合优化.md`）。跟四类边框裁决
// （BorderReviewPanel/BORDER_REVIEW_SPECS）**形状不同**，所以单独一套类型 +
// 单独一个面板：那四类是"一张图 + 一排按钮选一档"，这里一张卡要答三件事
// （是不是抬头 / 抬高几格 / 首字有没有被切掉），一排按钮装不下。
//
// 归 Step3 页：抬头**终判在 Step3**（用户 2026-09-12 定）。页级"抬头标注"卡
// （kind=head）同日也从 Step1 搬过来，跟列级共用一张卡的两个 tab——两级是
// 同一件事的粗细两档（页级粗筛找出抬头页 → 列级精标格数），分在两个 Step
// 的页面上，人要来回跳。

export interface HeadColCard {
  id: string
  kind: 'headcol'
  book: string
  page: number
  col: number
  img: string
  /** 现役算法的判定，作对照显示；几何量同时画进图（见下）。 */
  det_raised: boolean
  det_n_raised: number | null
  det_top_slack: number | null
  /** 本列抬头内边框的页面 y；**null = Step1 没探到**（vol02 全册都是 null）。 */
  det_hr_inner: number | null
  det_first_cell: { slot: number; kind: string; y0: number } | null
  /** 内边框上方的字墨行数（已剔除外边框那类贯通横线）。 */
  ink_rows: number
  /** Step1 `detect_head_raise` 探到抬头框——**权威判据**（18 列金标 15 命中零误报）。 */
  detected: boolean
  /** 探测器没报、但框上字墨很多 → **疑似漏检**，优先人裁。不是抬头判据。 */
  suspect: boolean
}

export interface HeadColCardsResponse {
  book: string
  kind: string
  pages: number[]
  n: number
  cards: HeadColCard[]
}

/** 一张卡人裁的三件事。`raised === 'no'` 时 `nRaised` 无意义（后端也不落盘）。 */
export interface HeadColState {
  raised?: 'yes' | 'no' | 'idk'
  nRaised?: number
  headCut?: 'ok' | 'cut' | 'idk'
  done?: boolean
}

export const RAISED_OPTS = [
  { key: 'yes', label: '是抬头', color: 'var(--ochre)', soft: 'var(--ochre-soft)' },
  { key: 'no', label: '不是', color: 'var(--ok)', soft: 'var(--ok-soft)' },
  { key: 'idk', label: '拿不准', color: 'var(--faint)', soft: 'var(--faint-soft)' },
] as const

/** 抬高几格。实测 n_raised 从没超过 1，但留到 3 档——版式先验不该写死在 UI 里。 */
export const N_RAISED_OPTS = [0, 1, 2, 3]

export const HEAD_CUT_OPTS = [
  { key: 'ok', label: '首字完整', color: 'var(--ok)', soft: 'var(--ok-soft)' },
  { key: 'cut', label: '首字被切', color: 'var(--zhu)', soft: 'var(--zhu-soft)' },
  { key: 'idk', label: '拿不准', color: 'var(--faint)', soft: 'var(--faint-soft)' },
] as const
