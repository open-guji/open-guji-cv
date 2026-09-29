// 按类别审（overview#247）：类别的前端口径 + 己已巳专用卡的键位 + 裁决 → 事件行。
//
// 类别表与归类规则的**正本在后端**（`review/cards.py::REVIEW_CLASSES` / `card_class`，一张卡只归
// 优先级最高的一类），响应里的 `classes` 给中文名与说明；这里只放「这一类的卡长什么样、按什么键」。
// 纯函数、不 import 运行时代码（只有 `import type`，node --experimental-strip-types 能直接跑，
// tests/test_review_by_class.py 用它守事件协议）。

/** 类别 → 帮助行（快捷键说明随类别换）。没列到的类别用 `DEFAULT_HELP`。 */
export const CLASS_HELP: Record<string, string> = {
  ji_yi_si: '己已巳：<b>1</b> 己 · <b>2</b> 已 · <b>3</b> 巳（定的是文意，照上下文选）· <b>4</b> 都不是（展开成普通卡） · '
    + '<b>N</b> 非字 · <b>S</b> 跳过 · <b>←/→</b> 翻卡',
  occluded: '印章遮挡：默认整理本字、字形不入库，没问题就直接「整组确认」；个别不对的在卡上改。'
    + '<b>1</b> 采信首选 · <b>N</b> 非字 · <b>S</b> 跳过 · <b>←/→</b> 翻卡',
  form_open: '义定形未定：只在「组内形」里挑本书刻的那个形。<b>1</b> 采信首选 · <b>2/3</b> 次选 · <b>S</b> 跳过 · <b>←/→</b> 翻卡',
  lib_miss: '库里没有：多半是生僻字，当前卡自动「查候选」（字体模板 + CNN 10 个）。'
    + '<b>1</b> 采信首选 · <b>2/3</b> 次选 · <b>T/C</b> 切分缺陷 · <b>Z</b> 小注当正文 · <b>N</b> 非字 · <b>S</b> 跳过 · <b>D</b> 原图破损',
  // 对齐改字层按细项分（overview#265）：键 = `replace_align:<细项>`，见 `classHelpKey`
  'replace_align:grid': '对齐改字层 · 网格：每张缺省<b>采信整理本</b>（下面那个字），只点掉异常的——'
    + '<b>点一下</b> 字形不完整 · <b>再点</b> 跳过 · <b>再点</b> 回到采信；「提交这一屏」一次写完整屏。',
  'replace_align:tail': '对齐改字层 · 列尾（第 20 格起，易混框线）：常见<b>下版框线混进字块</b>（<b>C</b> 有噪声）'
    + '或<b>末字被切掉</b>（<b>T</b> 字形不完整）。<b>1</b> 采信首选 · <b>2/3</b> 次选 · <b>Z</b> 小注当正文 · '
    + '<b>N</b> 非字 · <b>S</b> 跳过 · <b>←/→</b> 翻卡',
}

export const DEFAULT_HELP = '<b>1</b> 采信首选 · <b>2/3</b> 选次选 · <b>T</b> 字形不完整 · <b>Z</b> 小注当正文 · '
  + '<b>C</b> 有噪声 · <b>N</b> 非字 · <b>S</b> 跳过 · <b>D</b> 原图破损 · <b>←/→</b> 翻卡。字一律按图上刻的录。'

/** 帮助行查 `CLASS_HELP` 用的键：对齐改字层带细项（`replace_align:grid` 等），其余就是类别键。 */
export function classHelpKey(cls: string, sub: string): string {
  return cls === 'replace_align' && sub ? `${cls}:${sub}` : cls
}

/** 切分缺陷几档（`done` 值）：改字时都要保住，见 `pickVerdict`。 */
export const DEFECT_DONES: ReadonlyArray<string> = ['truncated', 'contaminated', 'jiazhu']

/**
 * 「小注当正文」（overview#265）：列尾双行小注被当成正文切成了一格。放在「字形不完整」那一组，
 * 事件照旧是 `v=seg_defect`、`quality=truncated`（下游当字形不完整处理：不入库、退 row_segment），
 * 只多一个 `reason` 说清是哪种不完整——下游不认这个字段，行为不变。
 */
export const JIAZHU_REASON = 'jiazhu_as_main'

/** 己已巳三选一：键 → 字。提示只讲文意，不讲字形（本族刻法不分）。 */
export const JYS_OPTIONS: ReadonlyArray<{ key: string; ch: string; hint: string }> = [
  { key: '1', ch: '己', hint: '自己、克己；天干（己丑、己卯）' },
  { key: '2', ch: '已', hint: '已經、而已、不得已' },
  { key: '3', ch: '巳', hint: '地支（癸巳、辰巳）、巳時' },
]

/** 「都不是」：展开成普通卡自己挑字（不发任何事件）。 */
export const JYS_NONE_KEYS: ReadonlyArray<string> = ['4', '0']

export function jysPickByKey(key: string): string | null {
  return JYS_OPTIONS.find((o) => o.key === key)?.ch ?? null
}

/** 这张卡用不用己已巳专用卡：归在这一类、且人没点「都不是」。 */
export function isJysCard(cls: string | undefined | null, opened: boolean): boolean {
  return cls === 'ji_yi_si' && !opened
}

/** 裁决的最小形状（与 ReviewPanel 的 `Verdict` 同构；这里不 import，保持本文件可被 node 直接跑）。 */
export interface VerdictLike {
  shape: string
  done: string
  ts?: number
  dwell?: number
  noGlyphLib?: boolean
  guess?: string
  /** 无匹配（近似字，overview#276）：Unicode 里没有真正对应的字，`shape` 只是字形最像、意思最近的那个。 */
  approx?: boolean
  /** 近似字的实际结构（IDS，可空）。只在 `approx` 时有意义。 */
  approxIds?: string
  /** 近似字备注（可空）。 */
  approxNote?: string
}

/**
 * 近似字的三个字段 → 事件 payload 片段（overview#276）。没勾 → 空对象：**老事件逐字段不变**，
 * 后端见不到 `approx` 键就按原样处理。`ids`/`note` 空串不写。
 */
export function approxFields(v: Pick<VerdictLike, 'approx' | 'approxIds' | 'approxNote'>): Record<string, unknown> {
  if (!v.approx) return {}
  const ids = (v.approxIds || '').trim()
  const note = (v.approxNote || '').trim()
  return { approx: true, ...(ids ? { ids } : {}), ...(note ? { note } : {}) }
}

/** 改字时要跟着裁决走的近似字字段（与 `noGlyphLib` 同一口径：人勾过的，改字不丢）。 */
export function keepApprox(prev: VerdictLike | undefined): Pick<VerdictLike, 'approx' | 'approxIds' | 'approxNote'> {
  if (!prev?.approx) return {}
  return { approx: true, approxIds: prev.approxIds, approxNote: prev.approxNote }
}

/**
 * 一格裁决 → `POST /api/events` 的一行（`kind=confirm`，靠 `v` 二次分流）。没裁（`done` 空）→ null。
 *
 * **所有卡型共用这一个函数**——己已巳专用卡三选一也走这里，产出与普通卡点同一个字**逐字段相同**
 * 的 `confirm` 行（`shape` = 选的字）：三选一定的是文意，字形照现有规则由下游处理
 * （`feedback/lookup.human_chars` 取人裁的字；己已巳在字形库里有样本封顶，`seed_admit` 对本族
 * 取事件的字而不是库里的形）。所以下游读事件的行为不变，不新造字段。
 *
 * `aiAcc`：是否采纳 AI 预选（`null` = 这一格没问过 AI，不写这个字段）。
 */
export function verdictRow(id: string, v: VerdictLike, aiAcc: boolean | null = null): Record<string, unknown> | null {
  if (!v.done) return null
  if (v.done === 'skip') return { id, v: 'skip' }
  if (v.done === 'damaged') {
    // 原图破损：字形不可辨，文本层出 □。`guess` 是括注用的「最像哪个字」，
    // 可空；不进字形库（后端 glyphdb_admit 只认 v==='confirm'）。
    return { id, v: 'damaged', guess: v.guess || '', client_ts: v.ts, dwell_ms: v.dwell }
  }
  if (v.done === 'non') return { id, v: 'not_a_char' }
  if (v.done === 'truncated' || v.done === 'contaminated') {
    return { id, v: 'seg_defect', quality: v.done, shape: v.shape || '', client_ts: v.ts, dwell_ms: v.dwell }
  }
  if (v.done === 'jiazhu') {
    return { id, v: 'seg_defect', quality: 'truncated', reason: JIAZHU_REASON, shape: v.shape || '',
             client_ts: v.ts, dwell_ms: v.dwell }
  }
  return {
    id, v: 'confirm', shape: v.shape,
    no_glyph_lib: !!v.noGlyphLib,
    client_ts: v.ts, dwell_ms: v.dwell,
    ...(aiAcc !== null ? { ai_accepted: aiAcc } : {}),
    ...approxFields(v),
  }
}

/**
 * 己已巳专用卡点了一个字之后的裁决——与普通卡 `setVerdict(i, ch)`（从候选改字）同一口径：
 * `done='1'`；原来标了切分缺陷（T/C）的保住缺陷档；`dwell` 首次裁决时记、之后不改；
 * 「字形不入库」勾选沿用。
 */
export function pickVerdict(ch: string, prev: VerdictLike | undefined, seenAt: number | undefined,
                            now: number): VerdictLike {
  const keepDefect = !!prev && DEFECT_DONES.includes(prev.done)
  const dwell = prev?.dwell !== undefined ? prev.dwell : (seenAt ? now - seenAt : undefined)
  return { shape: ch, done: keepDefect ? prev!.done : (ch ? '1' : ''), ts: now, dwell, noGlyphLib: prev?.noGlyphLib,
           ...keepApprox(prev) }
}

/** 上下文一格显示什么字：缺省整理本优先（`text`），开了「刻本读法」才用 `char`。 */
export function ctxChar(s: { char?: string | null; text?: string | null }, keben: boolean): string {
  return (keben ? s.char : (s.text ?? s.char)) || '□'
}

// ── 对齐改字层 · 网格（overview#265）───────────────────────────────────
//
// 用户审 vol03：「对齐改字层」确认了字的 197 张里 195 张就等于整理本对位字。所以这一类的非列尾
// 部分一屏摆几十张缩略图、缺省「采信整理本」，人只点掉异常的。点一下 → 字形不完整，再点 → 跳过，
// 再点回到采信。提交一次写完整屏，每格的事件与逐张卡上做同一件事**逐字段相同**：
// 采信 = 普通卡按 1（候选第一位就是整理本字）→ `pickVerdict(整理本字)`；
// 字形不完整 = 按 T（`{shape:'', done:'truncated'}`）；跳过 = 按 S。都经 `verdictRow` 出行。

export type GridState = 'accept' | 'truncated' | 'skip'
export const GRID_CYCLE: ReadonlyArray<GridState> = ['accept', 'truncated', 'skip']

export function nextGridState(s: GridState | undefined): GridState {
  const i = GRID_CYCLE.indexOf(s ?? 'accept')
  return GRID_CYCLE[(i + 1) % GRID_CYCLE.length]
}

/** 网格一格的裁决（与逐张卡同一口径）。`ref` = 整理本字；采信却没有整理本字 → null（不提交）。 */
export function gridVerdict(state: GridState, ref: string | null | undefined, seenAt: number | undefined,
                            now: number): VerdictLike | null {
  if (state === 'skip') return { shape: '', done: 'skip', ts: now }
  if (state === 'truncated') {
    return { shape: '', done: 'truncated', ts: now, dwell: seenAt ? now - seenAt : undefined }
  }
  return ref ? pickVerdict(ref, undefined, seenAt, now) : null
}

/**
 * 整屏 → 事件行。`aiAcc(card, shape)` 与逐张提交同一个口径（`ai.ts::aiAccepted`；这里不 import
 * 运行时代码，由调用方传进来，缺省当「没问过 AI」）。
 */
export function gridRows<C extends { id: string; ref?: { char?: string | null } | null }>(
  cards: ReadonlyArray<C>, states: Record<string, GridState | undefined>, seenAt: number | undefined, now: number,
  aiAcc: (c: C, shape: string) => boolean | null = () => null,
): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = []
  for (const c of cards) {
    const v = gridVerdict(states[c.id] ?? 'accept', c.ref?.char, seenAt, now)
    if (!v) continue
    const row = verdictRow(c.id, v, v.done === '1' ? aiAcc(c, v.shape) : null)
    if (row) rows.push(row)
  }
  return rows
}

// ── 提交只收当前屏（overview#265 补丁）──────────────────────────────────
//
// 旧毛病：先按「全部」载入，印章遮挡卡的默认裁决（整理本字／非字）在 `load()` 里登记成 touched；
// 切到别的类别再点「提交裁决」，这些**屏上根本没有**的默认行跟着静默提交（vol03 实测多出 30 行）。
// 现在两道：提交只收当前屏上显示着的 touched 卡（`screenRows`）；切换类别／细项时，不在新一屏上的
// touched 一律丢掉（`dropOffScreen`）——载入时预填的默认裁决悄悄丢，人亲手点过的也丢，但报出条数。

/** 当前屏 → 事件行：只收 `cards` 里本轮动过（`touched`）、有裁决的卡，按屏上顺序。 */
export function screenRows<C extends { id: string }>(
  cards: ReadonlyArray<C>, verdicts: Record<string, VerdictLike | undefined>, touched: ReadonlySet<string>,
  aiAcc: (c: C, shape: string) => boolean | null = () => null,
): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = []
  for (const c of cards) {
    const v = verdicts[c.id]
    if (!v?.done || !touched.has(c.id)) continue
    const row = verdictRow(c.id, v, aiAcc(c, v.shape))
    if (row) rows.push(row)
  }
  return rows
}

/**
 * 切换类别／细项时该丢的 touched：不在新一屏（`keep`）上的全部。`human` = 其中人亲手点过的
 * （不在 `auto` 里——`auto` 是载入时预填默认裁决登记的那些），调用方要把条数报给人。
 */
export function dropOffScreen(keep: ReadonlySet<string>, touched: ReadonlySet<string>,
                              auto: ReadonlySet<string>): { dropped: string[]; human: string[] } {
  const dropped = [...touched].filter((id) => !keep.has(id))
  return { dropped, human: dropped.filter((id) => !auto.has(id)) }
}
