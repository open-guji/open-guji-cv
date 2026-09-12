// 对应 GET /api/border-review/cards?kind=pageline 与 /api/border-review/verdicts。
// 整页下版框偏移金标：linebot 逐列坐标金标抽查发现窄列裁剪图容易把字缝
// 认成版框墨条、且误判整页同向——这张卡改成整页通栏带，一页拖一条线
// （保留现役斜率，只调整整体偏移量），比逐列点快也更看得清。

export interface PageLineCard {
  id: string
  kind: 'pageline'
  book: string
  page: number
  page_w: number
  crop_top: number
  y_left: number    // 现役线左端点 y，带坐标（crop_top 同一原点）
  y_right: number   // 现役线右端点 y，带坐标
  img: string
}

export interface PageLineCardsResponse {
  book: string
  kind: string
  pages: number[]
  n: number
  cards: PageLineCard[]
}

export interface PageLineVerdict {
  verdict: string    // moved / ok / no_line
  offset?: number | null
}

export interface PageLineVerdictsResponse {
  batch: string
  n: number
  verdicts: Record<string, PageLineVerdict>
}
