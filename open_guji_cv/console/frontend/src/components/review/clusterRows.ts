import type { ReviewCard, ReviewTileCluster } from '../../types/review'

// 组内按形聚簇的提交展开（overview #166），见 ClusterGrid.tsx。

export type Group = { tiles: ReviewCard[]; clusters?: ReviewTileCluster[] }

/** 这一组屏上所有可提交格的 id（聚簇时是各簇全部成员）。 */
export function groupCellIds(g: Group): string[] {
  if (g.clusters) return g.clusters.flatMap((c) => c.members.map((m) => m.id))
  return g.tiles.map((t) => t.id)
}

/**
 * 选中的格 → confirm 事件行。聚簇时每行多带 `via: cluster:<id>` 与簇大小。
 * `extra`：整组共用的附加字段——「无匹配（近似字）」勾上时是 `approxFields(...)` 的产出
 * （`approx/ids/note`，overview#276）；不传则事件逐字段与原来相同。
 */
export function groupRows(g: Group, dropped: Set<string>, shape: string, now: number,
                          extra: Record<string, unknown> = {}) {
  const base = { v: 'confirm', shape, client_ts: now, ...extra }
  // 印章遮挡格一律不入字形库（2026-09-30）
  const occ = new Set(g.tiles.filter((t) => t.occluded).map((t) => t.id))
  const noLib = (id: string) => ({ no_glyph_lib: occ.has(id) })
  if (!g.clusters) {
    return g.tiles.filter((t) => !dropped.has(t.id)).map((t) => ({ id: t.id, ...base, ...noLib(t.id) }))
  }
  return g.clusters.flatMap((c) => c.members.filter((m) => !dropped.has(m.id))
    .map((m) => ({ id: m.id, ...base, ...noLib(m.id), via: `cluster:${c.id}`, cluster_n: c.n })))
}
