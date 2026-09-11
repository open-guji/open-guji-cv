import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listBooks } from '../api/registry'
import type { Book } from '../types/registry'

// D2：首页——最近在整理的书 + 最近进展（方案 §二 `/`）。
// 第一版先列出全部书，"最近"的排序与"最近进展"摘要留待接入 /api/status 之后再做。
export function HomePage() {
  const [books, setBooks] = useState<Book[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listBooks().then(setBooks).catch((e) => setError(String(e)))
  }, [])

  return (
    <div className="card">
      <h2>最近在整理的书</h2>
      {error && <p className="error">{error}</p>}
      {!books && !error && <p className="muted">加载中…</p>}
      {books && (
        <ul className="book-list">
          {books.map((b) => (
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
