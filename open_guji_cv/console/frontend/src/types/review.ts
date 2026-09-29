// 对应 GET /api/review/cards 等，字段照 v1 static/js/panels/review.js 用法反推
// （原样复用后端契约，见方案 §一）。

export interface ReviewCardRef {
  char?: string
  op?: string
  form?: string
}

export interface ReviewCardDb {
  verdict: string
  cov: number
  candidates?: Array<[string, number]>
}

export interface ReviewCardCtx {
  char?: string
  margin?: number
  source?: string
  llm_suggestion?: string | null
}

export interface ReviewCardForm {
  state: 'open' | string
  semantic: string
  forms: string[]
  human?: Record<string, number>
  lib?: Array<[string, number]>
}

/** 词典严格异体分组（方案-词典加AI接入管线 §三 `groups`）：组内是同一个字的不同写法。 */
export interface AiGroup {
  id: string
  members: string[]
  why: string
}

export interface AiDropReason {
  c: string
  why: string
}

export interface AiRankItem {
  group: string   // 对应 AiGroup.id
  p: number
  why: string
}

/**
 * Step6 AI 判断层证据（方案 §三）。只对「问过 AI」的格有——图像两路不一致
 * 或缺一路的格，北行约 11%。没有这个字段（`card.ai` 缺失）的书（四庫等）
 * 卡片按老逐像素行为走，不显示 AI 部分。
 */
export interface AiEvidence {
  runs: number
  drop: string[]
  drop_why: AiDropReason[]
  rank: AiRankItem[]
  confidence: string        // 高 | 中 | 低
  need_human: string
  conflict_with_img: boolean   // AI 首组不含图像共识 → 标「疑似刻本讹字/整理本改字」
  /** 各次运行首组的代表字；两次不一致时标「AI 拿不准」，列出这里的两个字
   * （2026-09-27 C 道暂拟字段，方案原稿未定，见 done 单）。 */
  runs_top: string[]
}

export interface ReviewCard {
  id: string
  page: number
  col: number
  slot: number
  sub?: string
  channel?: string
  patch: string
  ref?: ReviewCardRef
  db?: ReviewCardDb
  ctx?: ReviewCardCtx
  /** 己/已/巳：按上下文定的建议字与依据（utils/ji_yi_si.py） */
  jys?: { char: string | null; why: string } | null
  ocr?: Array<[string, number]>
  doubts?: string[]
  form?: ReviewCardForm
  /** Step6-AI 三层证据：词典分组（`groups`）与 AI 排序/排除/把握度（`ai`）。
   * 两者都缺失 = 这一格没接 Step6-AI（四庫等书恒缺）。 */
  groups?: AiGroup[] | null
  ai?: AiEvidence | null
  /** 借库书的「AI 首选」（书 yaml `params.review.first_pick` 开了才有；四庫、北行恒缺）。
   * 任务书-C-借库书人审首选改CNN原型（2026-09-27），装配见 `review/borrow_first.py`。 */
  first?: FirstPick | null
  /** 印章／污损遮挡格（Step7 `occluded_gate`，overview#195）：默认字 = 整理本字（坐标对位优先），
   * 字形一律不入库；`ref_blank` = 整理本这一位是空格（印章切出来的假格），默认「非字」。 */
  occluded?: { char: string; via: string | null; ref_blank: boolean } | null
  /** 库给的字靠的是近似例（人裁勾过「无匹配（近似字）」的刻例，overview#276）；Step7 evidence.approx。 */
  approx?: { source: string; via: string; exemplar: string | null; ids: string | null; note: string | null } | null
  /** 按类别审（overview#247）：请求带了 `cls` 才有。一张卡只归优先级最高的一类。 */
  cls?: string
  /** 类别细项（overview#265）：目前只有「对齐改字层」有——grid / tail / manual。 */
  cls_sub?: string
}

/** 类别表的一行（后端 `REVIEW_CLASSES`，按优先级排）。 */
export interface ReviewClassMeta {
  key: string
  label: string
  hint: string
}

export interface FirstPick {
  /** 默认首选字（`cnn` = CNN 原型检索首位；`rrf` = 像素与 CNN 名次融合首位）。 */
  char: string | null
  mode: 'cnn' | 'rrf'
  /** 像素比对（5-a，字形库）首位。 */
  pixel: string | null
  /** CNN 原型检索首位。 */
  cnn: string | null
  /** 两路首位是否一致；任一路缺席为 `null`。 */
  agree: boolean | null
  cnn_candidates: Array<[string, number]>
  /** CNN 首位的原型来自本书自有库（own）还是借来的库（borrow，冷启动）。 */
  proto_src?: 'own' | 'borrow' | null
}

export interface ReviewCardsResponse {
  cards: ReviewCard[]
  blocked?: unknown[]
  /** 全书所有批次已裁过的字位数（后端跨批次去重）。skip_decided 开时这些卡已被跳过。 */
  n_decided?: number
  truncated?: boolean
  /** 请求带了 `doubt`（哪怕是 `*`）才有（overview#215）：码 → 卡数。口径 = 过了 only／
   * 已裁去重／顺序闸、还没按 doubt 筛的那批，不受 `limit` 截断；`_none` = 一个码都没有。 */
  doubt_counts?: Record<string, number>
  /** 参与 doubt 计数的卡数（一张卡多个码只算一次）。 */
  doubt_total?: number
  /** 请求带了 `cls`（哪怕是 `*`）才有（overview#247）：类别 → 剩余张数，口径同 `doubt_counts`，
   * 但一张卡只记一类。 */
  class_counts?: Record<string, number>
  class_total?: number
  classes?: ReviewClassMeta[]
  /** 类别细项计数（overview#265）：`{replace_align: {grid, tail, manual}}`，口径同 `class_counts`。 */
  class_sub_counts?: Record<string, Record<string, number>>
  class_subs?: Record<string, ReviewClassMeta[]>
}

/**
 * 按字种批审（`group=char`，任务书-C-待审卡按字种批审 2026-09-27）：
 * 一个字种一组，`tiles` 是排好序（最不像排最前）的样例，`n` 是这组真实的
 * 待审格总数（可能大于 `tiles.length`，`truncated` 标出来）。
 */
export interface ReviewCardGroupPage {
  page: number
  n: number
}

export interface ReviewCardGroup {
  /** AI 首选字；三路证据都没有时为 `null`，前端标"未识别"。 */
  char: string | null
  /** 非空 = 这组的首选字与整理本对齐字不同，单独成组，**不与同字种的组混**。 */
  ref_char: string | null
  n: number
  pages: ReviewCardGroupPage[]
  /** 聚簇开着时是各簇代表图（与 `clusters` 下标对齐），否则是组内样例。 */
  tiles: ReviewCard[]
  truncated: boolean
  /** 组内按形聚簇（overview #166）：只在聚簇开着时有。 */
  clusters?: ReviewTileCluster[]
  n_clusters?: number
}

/** 组内一簇（overview #166）：代表图是 `tiles[i]`，`members[0]` 也是它。 */
export interface ReviewTileCluster {
  /** 簇 id = 代表图的格 id；提交事件记 `via: cluster:<id>`。 */
  id: string
  n: number
  members: { id: string; patch: string; page: number; sim: number | null }[]
}

/** 响应顶层的聚簇摘要（只在聚簇开着时有）。 */
export interface ReviewClusterSummary {
  thr: number
  n_groups: number
  n_clusters: number
  n_cells: number
  n_with_emb: number
}

export interface ReviewCardsGroupedResponse {
  book: string
  mode: 'char'
  n_total: number
  n_decided?: number
  blocked?: unknown[]
  groups: ReviewCardGroup[]
  cluster?: ReviewClusterSummary
}

/**
 * 按形聚类分组（`group=shape`，任务书-C-批审按形聚类分组 2026-09-27）：
 * 先按形近对表把互相混淆的字种池化（`pool`，如 "今+令"），池内再用 CNN
 * embedding 按形状聚类拆开——同一个池可能拆成好几组，每组是一个真实形状。
 */
export interface ReviewMajority {
  char: string
  n: number
}

export interface ReviewShapeGroup {
  /** 池标签（形近对合并后的字种，如 "今+令"；没有形近搭档就是单字本身）。 */
  pool: string
  /** 建议字：整理本对齐字的多数票；两路证据都没有时为 `null`（未识别组）。 */
  char: string | null
  /** 另外几个候选字（含建议字本身），供一键改成别的字，封顶 3 个。 */
  candidates: string[]
  ai_majority: ReviewMajority | null
  ref_majority: ReviewMajority | null
  /** 组内多数票（取 `ref_majority` 优先）占 n 的比例。 */
  purity: number
  /** 这组是不是真走了 embedding 聚类拆出来的（`false` = 池没有形近搭档、
   * CNN 不可用、池太大或聚不出来，退化成等同 `group=char` 的一组）。 */
  clustered: boolean
  n: number
  pages: ReviewCardGroupPage[]
  tiles: ReviewCard[]
  truncated: boolean
  clusters?: ReviewTileCluster[]
  n_clusters?: number
}

export interface ReviewCardsShapeResponse {
  book: string
  mode: 'shape'
  /** CNN embedding 是否可用——`false` 时全部组退化成 `group=char` 等效分组，
   * `hint` 给出补救命令，不阻塞控制台。 */
  cluster_ready: boolean
  hint: string | null
  n_total: number
  n_decided?: number
  blocked?: unknown[]
  groups: ReviewShapeGroup[]
  cluster?: ReviewClusterSummary
}

export interface ReviewVerdict {
  shape: string
  done: string
  ts?: number
  dwell?: number
  noGlyphLib?: boolean
}

export interface ReviewVerdictsResponse {
  verdicts: Record<string, ReviewVerdict>
}

export interface RareCandidate {
  char: string
  score: number
  py?: string
  font?: string
  ids?: string
  cp?: string
  std?: string
  std_freq?: number
  freq?: number
  gloss?: string
  zi: string
  /** 结构解释（ids_struct 口径）：{top: '⿰', slots: {L: '言', R: '俞'}}；独体 top='独体' */
  struct?: { top: string; slots: Record<string, string> }
  near?: { char: string; kind: string; cos: number; detail: string }[]
  gw?: { name: string; source: string; cos: number; url: string }
}

export interface AroundSlot {
  /** 刻本这边的读法（定字 → 库 → OCR）。 */
  char?: string
  review?: boolean
  source?: string
  /** 整理本在这一格对位的字（align_ref；对不上为 null）。 */
  ref?: string | null
  /** 显示用：有整理本字用整理本，否则退回 `char`（#247）。 */
  text?: string | null
  /** `text` 取自哪：ref | coord | 定字链的 source。 */
  text_src?: string
}

export interface AroundContext {
  slots: AroundSlot[]
  at: number
}
