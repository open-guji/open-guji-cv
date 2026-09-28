import { useSyncExternalStore } from 'react'
import { api, ApiError } from './client'
import type { ConsumeResult } from '../domain'

export interface EventsInBody {
  batch: string
  step: string
  unit?: string
  kind?: string
  events: Array<Record<string, unknown>>
  consume?: boolean
  /** 幂等键。`postEvents` 自己填，调用方不用管。 */
  request_id?: string
}

export interface EventsOut extends ConsumeResult {
  appended: number
  batch: string
  total: number
  unrouted?: unknown
  /** 后端认出这是同一 request_id 的重复请求，没再写。 */
  duplicate?: boolean
}

// 部署重启（约 10–30 秒）期间写请求会失败。失败的这批**留在内存里**每 5 秒重发，
// 最多 2 分钟；每批一个 request_id，后端按它去重，所以「第一次其实写成功、只是
// 响应丢了」的重发也只落一份。
export const RETRY_INTERVAL_MS = 5000
export const RETRY_MAX_MS = 120000

let pending = 0
const listeners = new Set<() => void>()
function bump(d: number) {
  pending += d
  listeners.forEach((l) => l())
}
/** 正在等服务器恢复、待重发的批数（横幅用）。 */
export function usePendingEvents(): number {
  return useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l) } },
    () => pending)
}

/** 网络错误（fetch 抛 TypeError）或 502/503/504 = 服务器暂时不可用，值得重试。
 * 4xx/500 是请求本身的问题，重发也没用，照旧立刻抛给调用方。 */
export function isTransient(e: unknown): boolean {
  if (e instanceof ApiError) return e.status === 502 || e.status === 503 || e.status === 504
  return e instanceof TypeError
}

function newRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

export async function postEvents(body: EventsInBody): Promise<EventsOut> {
  const payload = JSON.stringify({ ...body, request_id: body.request_id ?? newRequestId() })
  const send = () => api<EventsOut>('/api/events', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: payload,
  })
  try {
    return await send()
  } catch (e) {
    if (!isTransient(e)) throw e
  }
  bump(1)
  try {
    const deadline = Date.now() + RETRY_MAX_MS
    for (;;) {
      await sleep(RETRY_INTERVAL_MS)
      try {
        return await send()
      } catch (e) {
        if (!isTransient(e)) throw e
        if (Date.now() >= deadline) throw e
      }
    }
  } finally {
    bump(-1)
  }
}
