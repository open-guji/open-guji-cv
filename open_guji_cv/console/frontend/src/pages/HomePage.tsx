import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listBooks } from '../api/registry'
import { WORKSPACE_CHANGED } from '../api/workspace'
import type { Book } from '../types/registry'

// D2：首页——最近在整理的书 + 最近进展（方案 §二 `/`）。
// 第一版先列出全部书，"最近"的排序与"最近进展"摘要留待接入 /api/status 之后再做。
export function HomePage() {
  const [books, setBooks] = useState<Book[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = () => {
      setBooks(null); setError(null)
      listBooks().then(setBooks).catch((e) => setError(String(e)))
    }
    load()
    // 热切工作区之后册列表整个换了一套，这张卡要跟着重取
    window.addEventListener(WORKSPACE_CHANGED, load)
    return () => window.removeEventListener(WORKSPACE_CHANGED, load)
  }, [])

  return (
    <div className="card">
      <h2>最近在整理的书</h2>
      {error && <p className="error">{error}</p>}
      {!books && !error && <p className="muted">加载中…</p>}
      {books && (
        <ul className="book-list">
          {/* 只列属于当前工作区的册：册列表是「引擎仓 books/ ∪ 工作区 books/」的
              并集，别的工作区那些册原图不在这儿，页数 0、点进去全空。 */}
          {books.filter((b) => b.in_workspace !== false).map((b) => (
            <li key={b.id}>
              <Link to={`/${b.id}/`}>{b.id} · {b.title}</Link>
              <span className="muted"> {b.n_pages} 页</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
