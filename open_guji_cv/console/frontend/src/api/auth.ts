// 身份委托给网站——OAuth 授权码 + PKCE，平台自己不存密码、不建账号表。
// 登录/登出都是**平台自己的**相对路径（`/auth/login`、`/auth/logout`，
// `console/routers/auth.py`），不是网站的地址——09-26 第二次改向后平台暂时
// 直连服务器 IP，不挂网站域名下，跳转/回调全在同一个源上完成。

import { ROOT_PATH } from './client'

export interface Identity {
  email: string
  role: string          // 网站原始角色：reviewer / editor / admin
  tier: 'reviewer' | 'admin'
}

/** 未登录时抛这个（区别于其它接口错误），调用方据此跳转登录，不是弹错误提示。 */
export class UnauthenticatedError extends Error {}

export async function getMe(): Promise<Identity> {
  const r = await fetch(`${ROOT_PATH}/api/auth/me`, { credentials: 'same-origin' })
  if (r.status === 401) throw new UnauthenticatedError('未登录')
  if (!r.ok) throw new Error(`拿不到身份：${r.status}`)
  return r.json() as Promise<Identity>
}

/** 跳去登录（整页导航，不是 fetch）。`next` 缺省当前页——登录完回得来。
 * `prompt === 'none'` 用于角色刷新到期后的静默重试（会话仍在但过了刷新间隔，
 * 后端 401；如果网站那边登录态还在，这一趟用户无感，登不动再退回交互式登录）。 */
export function goToLogin(opts?: { next?: string; prompt?: 'none' }): void {
  const next = opts?.next ?? window.location.pathname + window.location.search
  const params = new URLSearchParams({ next })
  if (opts?.prompt) params.set('prompt', opts.prompt)
  window.location.href = `${ROOT_PATH}/auth/login?${params.toString()}`
}

export function goToLogout(): void {
  window.location.href = `${ROOT_PATH}/auth/logout`
}
