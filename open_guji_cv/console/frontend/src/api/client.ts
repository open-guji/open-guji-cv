// 共用底层，对应 v1 static/js/api.js。原样搬（v1 v2 API 契约不变，见方案 §一）。

export const STATUS_MARK: Record<string, string> = {
  fresh: '✓', stale: '~', missing: '·', failed: '✗', blocked: '⊘',
}

/** 本页面的工作区 id——**从 URL 第一段读**（`/<ws>/<book>/step/...`）。
 *
 * 用户 2026-09-15：「每个 workspace 可以有个 id，然后这个 id 应该直接反映在
 * url 上，而不是隐藏在浏览器 tab 里。这样更直观。」
 *
 * 放 URL 比放 sessionStorage 好在：看得见自己在哪个工作区、链接能直接发给别人、
 * 能收藏、刷新和前进后退都不丢。两个标签页各开各的工作区照样成立——它们的
 * URL 本来就不同，天然隔离，还不依赖存储可不可用。
 *
 * 返回 null = URL 上没有（比如根路径），服务端按自己的 `GUJI_WORKSPACE` 来。 */
export function currentWorkspaceId(): string | null {
  const seg = window.location.pathname.split('/').filter(Boolean)[0]
  if (!seg) return null
  // 这几段是没有工作区前缀的顶级路由，别把它们当成工作区 id
  if (seg === 'glyphlib' || seg === 'variantlib') return null
  return decodeURIComponent(seg)
}

/** 给**图片类 URL** 带上工作区。
 *
 * `<img src>` 发不出自定义请求头，所以图片出口只能把工作区放查询串里。
 * 服务端中间件头和 `ws=` 两边都认（console/middleware.py）。
 * 凡是要塞进 `src`／`href`／`window.open` 的 /api 图片 URL，都过一道这个。 */
export function withWorkspace(url: string): string {
  const ws = currentWorkspaceId()
  if (ws === null) return url
  return url + (url.includes('?') ? '&' : '?') + 'ws=' + encodeURIComponent(ws)
}

export async function api<T = unknown>(path: string, opts?: RequestInit): Promise<T> {
  // 每个请求都带上本标签页的工作区。服务端据此解析 products / cache /
  // 字形库等所有根（console/middleware.py），不持有「当前工作区」。
  const ws = currentWorkspaceId()
  const headers = new Headers(opts?.headers)
  if (ws !== null) headers.set('X-Guji-Workspace', ws)
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
