import { useEffect, useState } from 'react'
import { getMe, goToLogin, UnauthenticatedError } from '../api/auth'
import type { Identity } from '../api/auth'

export type IdentityState =
  | { status: 'loading' }
  | { status: 'ok'; identity: Identity }
  | { status: 'unauthenticated' }
  | { status: 'error'; message: string }

/** 我是谁。未登录（或会话过了角色刷新间隔）时**跳到平台自己的 `/auth/login`**
 * （OAuth 授权码流程的起点，`console/routers/auth.py`）——控制台自己不画登录
 * 表单，那套在网站那边（09-26 第二次改向：平台直连服务器 IP，不能转发网站
 * cookie，改标准 OAuth2）。
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
        goToLogin()
      } else {
        setState({ status: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    })
    return () => { alive = false }
  }, [])

  return state
}
