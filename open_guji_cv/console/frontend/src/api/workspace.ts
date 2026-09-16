import { api, getWorkspacePref, setWorkspacePref } from './client'

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

/** 本标签页当前在哪个工作区（服务端按请求头回，所以回的就是本标签页的）。 */
export const getWorkspace = () => api<WorkspaceState>('/api/workspace')

export const WORKSPACE_CHANGED = 'guji:workspace-changed'

/** 切工作区 = 改本标签页自己的偏好，**不通知服务端**——下一个请求自然就带
 * 新的了。所以另一个标签页完全不受影响，两个页面可以同时在两个工作区上干活。 */
export function switchWorkspace(path: string): void {
  setWorkspacePref(path)
  window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGED, { detail: path }))
}

export { getWorkspacePref }
