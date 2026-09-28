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
    + '<b>1</b> 采信首选 · <b>2/3</b> 次选 · <b>T/C</b> 切分缺陷 · <b>N</b> 非字 · <b>S</b> 跳过 · <b>D</b> 原图破损',
}

export const DEFAULT_HELP = '<b>1</b> 采信首选 · <b>2/3</b> 选次选 · <b>T</b> 字形不完整 · <b>C</b> 有噪声 · '
  + '<b>N</b> 非字 · <b>S</b> 跳过 · <b>D</b> 原图破损 · <b>←/→</b> 翻卡。字一律按图上刻的录。'

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
  return {
    id, v: 'confirm', shape: v.shape,
    no_glyph_lib: !!v.noGlyphLib,
    client_ts: v.ts, dwell_ms: v.dwell,
    ...(aiAcc !== null ? { ai_accepted: aiAcc } : {}),
  }
}

/**
 * 己已巳专用卡点了一个字之后的裁决——与普通卡 `setVerdict(i, ch)`（从候选改字）同一口径：
 * `done='1'`；原来标了切分缺陷（T/C）的保住缺陷档；`dwell` 首次裁决时记、之后不改；
 * 「字形不入库」勾选沿用。
 */
export function pickVerdict(ch: string, prev: VerdictLike | undefined, seenAt: number | undefined,
                            now: number): VerdictLike {
  const keepDefect = prev?.done === 'truncated' || prev?.done === 'contaminated'
  const dwell = prev?.dwell !== undefined ? prev.dwell : (seenAt ? now - seenAt : undefined)
  return { shape: ch, done: keepDefect ? prev!.done : (ch ? '1' : ''), ts: now, dwell, noGlyphLib: prev?.noGlyphLib }
}

/** 上下文一格显示什么字：缺省整理本优先（`text`），开了「刻本读法」才用 `char`。 */
export function ctxChar(s: { char?: string | null; text?: string | null }, keben: boolean): string {
  return (keben ? s.char : (s.text ?? s.char)) || '□'
}
