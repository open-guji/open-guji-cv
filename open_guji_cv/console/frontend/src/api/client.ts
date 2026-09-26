// 共用底层，对应 v1 static/js/api.js。原样搬（v1 v2 API 契约不变，见方案 §一）。

export const STATUS_MARK: Record<string, string> = {
  fresh: '✓', stale: '~', missing: '·', failed: '✗', blocked: '⊘',
}

/** 挂在反向代理前缀下时用（如 `/collate`，build 时 `VITE_ROOT_PATH` 定，见
 * `vite.config.ts` 头注）——浏览器发出的每一个绝对路径请求（fetch／`<img src>`／
 * Router 导航）都要带这个前缀，缺省空串就是本机单独跑控制台的老行为。
 * 与后端 `guji console --root-path` 是同一个值，但各自独立配置：后端那个是给
 * uvicorn 生成正确的绝对 URL 用（反向代理已经把前缀剥掉转发过来），这个是给
 * **浏览器发出的请求**用（浏览器看到的地址栏就在 `/collate/...` 下，不剥前缀）。*/
export const ROOT_PATH: string = (import.meta.env.VITE_ROOT_PATH ?? '').replace(/\/$/, '')

function withRoot(path: string): string {
  return ROOT_PATH ? ROOT_PATH + path : path
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
  let path = window.location.pathname
  if (ROOT_PATH && path.startsWith(ROOT_PATH)) path = path.slice(ROOT_PATH.length)
  const seg = path.split('/').filter(Boolean)[0]
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
  const rooted = withRoot(url)
  const ws = currentWorkspaceId()
  if (ws === null) return rooted
  return rooted + (rooted.includes('?') ? '&' : '?') + 'ws=' + encodeURIComponent(ws)
}

export async function api<T = unknown>(path: string, opts?: RequestInit): Promise<T> {
  // 每个请求都带上本标签页的工作区。服务端据此解析 products / cache /
  // 字形库等所有根（console/middleware.py），不持有「当前工作区」。
  const ws = currentWorkspaceId()
  const headers = new Headers(opts?.headers)
  if (ws !== null) headers.set('X-Guji-Workspace', ws)
  const r = await fetch(withRoot(path), { ...opts, headers })
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
