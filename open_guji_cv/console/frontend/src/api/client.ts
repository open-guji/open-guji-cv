// 共用底层，对应 v1 static/js/api.js。原样搬（v1 v2 API 契约不变，见方案 §一）。

export const STATUS_MARK: Record<string, string> = {
  fresh: '✓', stale: '~', missing: '·', failed: '✗', blocked: '⊘',
}

export async function api<T = unknown>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(path, opts)
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
