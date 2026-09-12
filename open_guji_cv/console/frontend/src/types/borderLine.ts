// 对应 GET /api/border-review/cards?kind=linebot 与 /api/border-review/verdicts。
// 下版框坐标金标：与 cols/head/outer/colborder 那四张"只点类别"的卡不同形状
// （这张要拖一条线），单独一套类型/组件，不往 BorderReviewCard 里硬塞坐标字段。

export interface BorderLineCard {
  id: string
  kind: 'linebot'
  book: string
  page: number
  col: number
  col_h: number
  y0: number          // 算法当前估的版框线，裁剪图坐标（拖动线的初值）
  raised: boolean
  img: string
}

export interface BorderLineCardsResponse {
  book: string
  kind: string
  pages: number[]
  n: number
  cards: BorderLineCard[]
}

export interface BorderLineVerdict {
  verdict: string    // moved / ok / no_line
  y?: number | null
}

export interface BorderLineVerdictsResponse {
  batch: string
  n: number
  verdicts: Record<string, BorderLineVerdict>
}
