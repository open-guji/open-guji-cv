// 身份委托给网站——这里只是薄薄一层：问后端「我是谁」（后端再转发 Cookie
// 去问网站 `/api/auth/me`），以及拿跳转用的地址（登录/登出入口）。
// 不在前端存密码、不做任何本地登录表单。

import { ROOT_PATH } from './client'

export interface Identity {
  email: string
  role: string          // 网站原始角色：reviewer / editor / admin
  tier: 'reviewer' | 'admin'
}

export interface AuthConfig {
  login_url: string
  logout_url: string
  root_path: string
}

/** 未登录时抛这个（区别于其它接口错误），调用方据此跳转登录，不是弹错误提示。 */
export class UnauthenticatedError extends Error {}

export async function getMe(): Promise<Identity> {
  const r = await fetch(`${ROOT_PATH}/api/auth/me`, { credentials: 'same-origin' })
  if (r.status === 401) throw new UnauthenticatedError('未登录')
  if (!r.ok) throw new Error(`拿不到身份：${r.status}`)
  return r.json() as Promise<Identity>
}

export async function getAuthConfig(): Promise<AuthConfig> {
  const r = await fetch(`${ROOT_PATH}/api/auth/config`, { credentials: 'same-origin' })
  if (!r.ok) throw new Error(`拿不到鉴权配置：${r.status}`)
  return r.json() as Promise<AuthConfig>
}
