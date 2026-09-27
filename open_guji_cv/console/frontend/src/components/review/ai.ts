// Step6-AI 卡片辅助：默认预选 / 排除折叠 / 两类标记。纯函数，抽出来跟
// candidates.ts 同一个理由——状态与渲染留给组件，判定逻辑单独摆出来方便看。
// 任务书-C-人审卡按AI预选（overview 2026-09-27）。
import type { AiEvidence, AiGroup, ReviewCard } from '../../types/review'

export function groupById(groups: AiGroup[] | null | undefined, id: string): AiGroup | undefined {
  return (groups || []).find((g) => g.id === id)
}

/** AI 首组（`ai.rank` 已按 p 降序；这里不再重排，信上游）。 */
export function topGroup(c: ReviewCard): { rank: AiEvidence['rank'][number]; group: AiGroup } | null {
  const top = c.ai?.rank?.[0]
  if (!top) return null
  const group = groupById(c.groups, top.group)
  if (!group) return null
  return { rank: top, group }
}

/**
 * 默认选中的字形：首组只有一个字才直接给出；多个字时由人看图定，
 * 这里不替审阅人选（返回 `null`），卡片只高亮这个组。
 *
 * 两次运行首组不一致（`disagreeingRuns` 非空，卡片标「AI 拿不准」）时也不
 * 默认选——AI 自己都没拿定主意，不该看着像已经选好了（2026-09-27 实测截图
 * 时发现：首组恰好单字会被默认选中，跟旁边的「拿不准」标记自相矛盾）。
 */
export function aiDefaultShape(c: ReviewCard): string | null {
  if (disagreeingRuns(c.ai)) return null
  const t = topGroup(c)
  if (!t) return null
  return t.group.members.length === 1 ? t.group.members[0] : null
}

/** 最终定的字是否落在 AI 首组里——「是否采纳 AI 预选」的判据（组内选哪个字都算采纳）。 */
export function aiAccepted(c: ReviewCard, finalShape: string): boolean | null {
  const t = topGroup(c)
  if (!t || !finalShape) return null
  return t.group.members.includes(finalShape)
}

/** 两次运行首组不一致 → 「AI 拿不准」，列出各次首组代表字（去重后 >1 个才算不一致）。 */
export function disagreeingRuns(ai: AiEvidence | null | undefined): string[] | null {
  const tops = ai?.runs_top || []
  if (tops.length < 2) return null
  return new Set(tops).size > 1 ? tops : null
}

/** 排除项的理由（找不到就是空字符串，卡片仍能展开、只是没有 why 文案）。 */
export function dropReason(ai: AiEvidence | null | undefined, ch: string): string {
  return (ai?.drop_why || []).find((d) => d.c === ch)?.why || ''
}
