import { api, currentWorkspaceId } from './client'

/** 一个可切换的工作区。`id` 是 URL 上露出来的那一段。 */
export interface WorkspaceEntry {
  id: string
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

/** 本页面当前在哪个工作区（服务端按请求头回，所以回的就是本页面的）。 */
export const getWorkspace = () => api<WorkspaceState>('/api/workspace')

/** 切工作区 = **换 URL 的第一段**，不通知服务端，也不存任何地方。
 * 由调用方拿这个结果去 `navigate()`。 */
export function workspaceHref(wsId: string, rest = '/'): string {
  return `/${encodeURIComponent(wsId)}${rest.startsWith('/') ? rest : '/' + rest}`
}

export { currentWorkspaceId }
