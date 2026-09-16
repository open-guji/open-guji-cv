// 共用底层，对应 v1 static/js/api.js。原样搬（v1 v2 API 契约不变，见方案 §一）。

export const STATUS_MARK: Record<string, string> = {
  fresh: '✓', stale: '~', missing: '·', failed: '✗', blocked: '⊘',
}

/** 本标签页的工作区（绝对路径）。空串 = 明确用仓内样本库；null = 没选过，
 * 服务端按它自己的 GUJI_WORKSPACE 环境变量来。
 *
 * **存在浏览器里，不存服务端**（用户 2026-09-15 定）：这样开两个标签页可以
 * 各自在不同工作区上干活。用 sessionStorage 而不是 localStorage——前者按
 * 标签页隔离，后者同源共享，用了就又变成「切一个全变」了。 */
const WS_KEY = 'guji.workspace'

export function getWorkspacePref(): string | null {
  try {
    return sessionStorage.getItem(WS_KEY)
  } catch {
    return null                      // 隐私模式/禁用存储：退回服务端默认
  }
}

export function setWorkspacePref(path: string | null): void {
  try {
    if (path === null) sessionStorage.removeItem(WS_KEY)
    else sessionStorage.setItem(WS_KEY, path)
  } catch {
    // 存不上就只在本次会话内存里生效（下面的 memo），不报错
  }
  memo = path
}

let memo: string | null | undefined

/** 给**图片类 URL** 带上工作区。
 *
 * `<img src>` 发不出自定义请求头，所以图片出口只能把工作区放查询串里。
 * 服务端中间件头和 `ws=` 两边都认（console/middleware.py）。
 * 凡是要塞进 `src`／`href`／`window.open` 的 /api 图片 URL，都过一道这个。 */
export function withWorkspace(url: string): string {
  const ws = memo !== undefined ? memo : getWorkspacePref()
  if (ws === null || ws === undefined) return url
  return url + (url.includes('?') ? '&' : '?') + 'ws=' + encodeURIComponent(ws)
}

export async function api<T = unknown>(path: string, opts?: RequestInit): Promise<T> {
  // 每个请求都带上本标签页的工作区。服务端据此解析 products / cache /
  // 字形库等所有根（console/middleware.py），不持有「当前工作区」。
  const ws = memo !== undefined ? memo : getWorkspacePref()
  const headers = new Headers(opts?.headers)
  if (ws !== null && ws !== undefined) headers.set('X-Guji-Workspace', ws)
  const r = await fetch(path, { ...opts, headers })
  if (!r.ok) {
    let t = await r.text()
    try {
      t = JSON.parse(t).detail || t
    } catch {
      // 不是 JSON，原样用文本
    }
    throw new Error(t)
  }
  return r.json() as Promise<T>
}

export function fmtDur(s: number | null | undefined): string {
  if (s == null) return ''
  return s < 60 ? `${s.toFixed(1)}s` : `${(s / 60).toFixed(1)}min`
}
