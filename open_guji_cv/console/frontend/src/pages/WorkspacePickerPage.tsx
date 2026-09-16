import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getWorkspace } from '../api/workspace'
import type { WorkspaceEntry } from '../api/workspace'

// 根路径 `/` 落在这里：URL 上还没有工作区 id，先让人选一个。
//
// 选完跳到 `/<ws>/`，此后工作区一直在地址栏第一段上摆着——看得见、能收藏、
// 能把链接直接发给人，前进后退也不丢（用户 2026-09-15：「应该直接反映在 url
// 上，而不是隐藏在浏览器 tab 里。这样更直观」）。
export function WorkspacePickerPage() {
  const [items, setItems] = useState<WorkspaceEntry[] | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    getWorkspace().then((w) => setItems(w.available)).catch((e) => setErr(String(e)))
  }, [])

  return (
    <div className="card">
      <h2>选一个工作区</h2>
      {err && <p className="error">{err}</p>}
      {!items && !err && <p className="muted">加载中…</p>}
      {items && items.length === 0 && (
        <p className="muted">
          没发现工作区。工作区是「有 <code>books/</code> 的目录」，
          放在当前 <code>GUJI_WORKSPACE</code> 的同级；也可以用
          <code>GUJI_WORKSPACE_DIRS</code> 显式指定。
        </p>
      )}
      {items && items.length > 0 && (
        <ul className="book-list">
          {items.map((w) => (
            <li key={w.id}>
              <Link to={`/${encodeURIComponent(w.id)}/`}>{w.id}</Link>
              <span className="muted">
                {' '}{w.books.length} 册{w.books.length ? `（${w.books.slice(0, 4).join('、')}${w.books.length > 4 ? '…' : ''}）` : ''}
                {' · '}{w.path}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
