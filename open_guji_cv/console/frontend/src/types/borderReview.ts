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
  // 这张卡问的是**哪个问题**（2026-09-18）。cols/head/outer 三类共用
  // `eventKind: 'verdict'` + `step: 'border_detect'`，路由无从分辨，此前
  // 三者全落进 `border-detection/column-split`——实测 siku 那个分片 205 条里
  // 70 条是 head 的 yes/no，而该分片本该全是 ok/miss/extra，档位都对不上。
  // 前端随裁决发出 `payload.question`，路由按它分流（feedback/routes.py）。
  // 命名法 `<step>.<对象>.<问什么>` 见《计划书-控制台四板块统一》§2.2。
  question: string
  options: VerdictOption[]
}> = {
  cols: {
    question: 'border_detect.page.vline_on_seam',
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
    question: 'border_detect.page.has_head_raise',
    // 2026-09-12 从 Step1 搬到 Step3，与「列级抬头精标」同卡两 tab，改名
    // 「页级抬头标注」——两级是同一件事的粗细两档，名字要能看出层级。
    title: '页级抬头标注',
    howto: '这是每页上版框那一条横带的原图，没有叠任何算法结果——这一档量的是 Step1 抬头框探测器的召回率，卡上印了机器判断人就会顺着点。判「这页有没有抬头」，判据是版框线本身有台阶，不是「有字比别的高」。判 yes 的页再切到「列级抬头精标」逐列标格数（那一档是要数格子，所以反过来必须叠线）。',
    eventKind: 'verdict',
    options: [
      { key: 'yes', label: '有抬头', color: 'var(--ochre)', soft: 'var(--ochre-soft)' },
      { key: 'no', label: '没有', color: 'var(--ok)', soft: 'var(--ok-soft)' },
      { key: 'idk', label: '拿不准', color: 'var(--faint)', soft: 'var(--faint-soft)' },
    ],
  },
  outer: {
    question: 'border_detect.page.outer_edge',
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
    question: 'column_warp.page.border_class',
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
