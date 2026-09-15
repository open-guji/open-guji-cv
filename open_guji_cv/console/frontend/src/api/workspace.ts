import { api } from './client'

/** 一个可切换的工作区。`books` 是它 books/ 下的册 id。 */
export interface WorkspaceEntry {
  path: string
  name: string
  books: string[]
  current: boolean
}

export interface WorkspaceState {
  workspace: string | null
  roots: Record<string, string>
  available: WorkspaceEntry[]
}

export const getWorkspace = () => api<WorkspaceState>('/api/workspace')

/** 热切工作区：后端改 GUJI_WORKSPACE 并重建进程内的 Store，**不重启进程**。
 * 有任务在跑时后端回 409（切了会把后半批产物写到另一个工作区）。 */
export const WORKSPACE_CHANGED = 'guji:workspace-changed'

export async function switchWorkspace(path: string) {
  const r = await api<WorkspaceState & { previous: string | null }>('/api/workspace', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  // 册列表、产物、字形库全都换了一套。凡是在 mount 时取过数据的视图都得重取——
  // 首页那张「最近在整理的书」就是只在 mount 取一次，不广播的话切完还显示旧
  // 工作区的册和页数（2026-09-15 实测）。
  window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGED, { detail: r }))
  return r
}
