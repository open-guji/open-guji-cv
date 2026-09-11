import { useEffect, useState } from 'react'
import { listBooks } from '../api/registry'
import type { Book } from '../types/registry'
import { GroupsPanel } from '../components/variants/GroupsPanel'

// 用户 2026-09-11 测试反馈 §4：字形库——统一总览本套书的字形库，把"组视图"
// 放进去。独立于书之外的顶级栏目（/glyphlib/），组视图本身仍按书查询，
// 这里加一个书选择器喂给它，组件逻辑不用改。
export function GlyphLibraryPage() {
  const [books, setBooks] = useState<Book[]>([])
  const [book, setBook] = useState('')

  useEffect(() => {
    listBooks().then((bs) => { setBooks(bs); if (bs[0]) setBook(bs[0].id) }).catch(() => {})
  }, [])

  return (
    <div>
      <div className="card">
        <h2>字形库 <span className="muted">统一总览本套书的字形库</span></h2>
        <label className="muted">册
          <select value={book} onChange={(e) => setBook(e.target.value)}>
            {books.map((b) => <option key={b.id} value={b.id}>{b.id} · {b.title}</option>)}
          </select>
        </label>
      </div>
      {book && <GroupsPanel book={book} />}
    </div>
  )
}
