// 对应 GET /api/border-review/cards 与 /api/border-review/verdicts。
// 四类裁决共用同一份卡片形状（分类型裁决：一张图 + N 档按钮，不带坐标拖拽）——
// 原先各自是 scripts/build_border_gold_reviews.py（cols/head/outer）与
// scripts/build_column_border_review.py（colborder）生成的 Artifact 网页，
// 用户 2026-09-11 定「以后完全不走 artifact，都走控制台」后搬进来。

export type BorderReviewKind = 'cols' | 'head' | 'outer' | 'colborder'

export interface BorderReviewCard {
  id: string
  kind: BorderReviewKind
  book: string
  page: number
  img: string
  // cols
  n_cols?: number
  // outer
  side?: 'top' | 'bottom'
  offset?: number
  // colborder
  col?: number
  end?: 'top' | 'bot'
  raised?: boolean
}

export interface BorderReviewCardsResponse {
  book: string
  kind: BorderReviewKind
  pages: number[]
  n: number
  cards: BorderReviewCard[]
}

export interface BorderReviewVerdictsResponse {
  batch: string
  n: number
  verdicts: Record<string, { verdict: string }>
}

export interface VerdictOption {
  key: string
  label: string
  color: string
  soft: string
}

export const BORDER_REVIEW_SPECS: Record<BorderReviewKind, {
  title: string
  howto: string
  eventKind: 'verdict' | 'border_class'
  options: VerdictOption[]
}> = {
  cols: {
    title: '界行切分裁决台',
    howto: '红色虚线是算法探到的界行。判它们是不是都落在字缝上——有的缝没被切到、或者线压在字上，都算没切对。',
    eventKind: 'verdict',
    options: [
      { key: 'ok', label: '都在缝上', color: 'var(--ok)', soft: 'var(--ok-soft)' },
      { key: 'miss', label: '有缝漏切', color: 'var(--zhu)', soft: 'var(--zhu-soft)' },
      { key: 'extra', label: '线压在字上', color: 'var(--zhu)', soft: 'var(--zhu-soft)' },
      { key: 'idk', label: '拿不准', color: 'var(--faint)', soft: 'var(--faint-soft)' },
    ],
  },
  head: {
    title: '抬头有无裁决台',
    howto: '这是每页上版框那一条横带的原图，没有叠任何算法结果。判「这页有没有抬头」——判据是版框线本身有台阶，不是「有字比别的高」。',
    eventKind: 'verdict',
    options: [
      { key: 'yes', label: '有抬头', color: 'var(--ochre)', soft: 'var(--ochre-soft)' },
      { key: 'no', label: '没有', color: 'var(--ok)', soft: 'var(--ok-soft)' },
      { key: 'idk', label: '拿不准', color: 'var(--faint)', soft: 'var(--faint-soft)' },
    ],
  },
  outer: {
    title: '外框外延裁决台',
    howto: '红色虚线是算法量出来的外条最外沿（外延）。判这条线的位置：压在最外沿上=对；还在墨条里面=偏内；跑到墨条外面的白纸上=偏外。',
    eventKind: 'verdict',
    options: [
      { key: 'ok', label: '在外沿上', color: 'var(--ok)', soft: 'var(--ok-soft)' },
      { key: 'in', label: '偏内', color: 'var(--zhu)', soft: 'var(--zhu-soft)' },
      { key: 'out', label: '偏外', color: 'var(--zhu)', soft: 'var(--zhu-soft)' },
      { key: 'none', label: '没有外框', color: 'var(--ochre)', soft: 'var(--ochre-soft)' },
      { key: 'idk', label: '拿不准', color: 'var(--faint)', soft: 'var(--faint-soft)' },
    ],
  },
  colborder: {
    title: '单列矫正·上下版框核校',
    howto: '一张卡是一列的一端（上端或下端）。图已经把两侧界行清掉了、只留文字带那一段宽度，并且一律转成「版框在上、字在下」。右边那条是沿水平方向的投影。只需要点一个类别，不用标坐标。',
    eventKind: 'border_class',
    options: [
      { key: 'clean', label: '有间隙', color: 'var(--ok)', soft: 'var(--ok-soft)' },
      { key: 'glued', label: '粘连', color: 'var(--zhu)', soft: 'var(--zhu-soft)' },
      { key: 'none', label: '没残墨', color: 'var(--indigo)', soft: 'var(--indigo-soft)' },
      { key: 'idk', label: '拿不准', color: 'var(--faint)', soft: 'var(--faint-soft)' },
    ],
  },
}
