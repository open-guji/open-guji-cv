import { useEffect, useState } from 'react'
import { getAuthConfig, getMe, UnauthenticatedError } from '../api/auth'
import type { Identity } from '../api/auth'

export type IdentityState =
  | { status: 'loading' }
  | { status: 'ok'; identity: Identity }
  | { status: 'unauthenticated' }
  | { status: 'error'; message: string }

/** 我是谁。未登录时**跳到网站登录入口**（地址来自 `/api/auth/config`，可配）——
 * 控制台自己不画登录页，登录整套都在网站那边（09-26 改向：不自建账号）。
 *
 * 跳转带 `next`，登录完网站把人送回来（网站那边要认这个参数——写进对接清单）。
 */
export function useIdentity(): IdentityState {
  const [state, setState] = useState<IdentityState>({ status: 'loading' })

  useEffect(() => {
    let alive = true
    getMe().then((identity) => {
      if (alive) setState({ status: 'ok', identity })
    }).catch((err) => {
      if (!alive) return
      if (err instanceof UnauthenticatedError) {
        setState({ status: 'unauthenticated' })
        getAuthConfig().then((cfg) => {
          const next = encodeURIComponent(window.location.href)
          const sep = cfg.login_url.includes('?') ? '&' : '?'
          window.location.href = `${cfg.login_url}${sep}next=${next}`
        }).catch(() => {
          // 连配置都拿不到——没法跳，至少别让页面停在「加载中」死等
        })
      } else {
        setState({ status: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    })
    return () => { alive = false }
  }, [])

  return state
}
