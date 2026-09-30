import { useEffect, useRef, useState } from 'react'
import { getVersion } from '../api/version'
import type { VersionInfo } from '../api/version'
import { usePendingEvents } from '../api/events'

const POLL_MS = 60000

/** 部署版本：侧栏角上显示当前版本，每分钟轮询，变了就顶部提示（不自动刷新）；
 * 另外在有写请求因服务器重启而暂存时提示「稍后自动重试」。 */
export function VersionInfoLine() {
  const [loaded, setLoaded] = useState<VersionInfo | null>(null)
  const [latest, setLatest] = useState<VersionInfo | null>(null)
  const [failed, setFailed] = useState(false)
  const first = useRef(true)
  const pending = usePendingEvents()

  useEffect(() => {
    let alive = true
    const tick = () => getVersion().then((v) => {
      if (!alive) return
      if (first.current) { first.current = false; setLoaded(v) }
      setLatest(v)
    }).catch(() => {
      // 重启间隙取不到很正常；首次就失败也算「加载时版本 = 开发版」，不弹提示
      if (alive && first.current) { first.current = false; setFailed(true) }
    })
    tick()
    const t = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const changed = !!(loaded && latest && latest.commit !== loaded.commit)
  const shown = latest ?? loaded
  const label = shown?.commit ? shown.commit : failed || shown ? '开发版' : '…'
  return (
    <>
      {(changed || pending > 0) && (
        <div className="version-banner" role="status">
          {pending > 0 && <span>服务器正在更新，稍后自动重试（{pending} 批待提交）</span>}
          {changed && latest && (
            <span>
              已更新到 {latest.commit ?? '开发版'}{latest.subject ? `（改动：${latest.subject}）` : ''}，刷新即可
              <button type="button" onClick={() => window.location.reload()}>刷新</button>
            </span>
          )}
        </div>
      )}
      <div className="sidebar-version muted" title={shown ? `部署于 ${shown.deployed_at}` : undefined}>
        cv {label}{shown?.commit ? ` · ${shown.deployed_at.replace('T', ' ').slice(0, 16)}` : ''}
      </div>
    </>
  )
}
