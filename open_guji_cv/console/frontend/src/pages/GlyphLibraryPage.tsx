import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listBooks } from '../api/registry'
import type { Book } from '../types/registry'
import { GroupsPanel } from '../components/variants/GroupsPanel'
import { LibSummaryPanel } from '../components/glyphlib/LibSummaryPanel'
import { LibCharTable } from '../components/glyphlib/LibCharTable'
import { LibCharDetail } from '../components/glyphlib/LibCharDetail'
import '../components/glyphlib/glyphlib.css'

// 字形库：本工作区（= 一本书）的字形库总览。用户 2026-09-11 §4 立栏目时只放了组视图，
// 要先按页跑任务才出内容，打开是空的；2026-09-25 字形库 02 卡补上总账 / 字表 / 单字页。
// tab、过滤、当前字都放 URL 查询串，链接能直接发给别人。
type Tab = 'summary' | 'chars' | 'char' | 'groups'

export function GlyphLibraryPage() {
  const [sp, setSp] = useSearchParams()
  const tab = (sp.get('tab') as Tab) || 'summary'
  const filter = sp.get('f') || 'all'
  const char = sp.get('c') || ''
  const set = (kv: Record<string, string>) => {
    const n = new URLSearchParams(sp)
    for (const [k, v] of Object.entries(kv)) { if (v) n.set(k, v); else n.delete(k) }
    setSp(n)
  }

  return (
    <div>
      <div className="card">
        <h2>字形库 <span className="muted">本书收了哪些字形：本书各刻例来源并成一套、按格去重</span></h2>
      </div>
      <div className="tabs">
        {([['summary', '总账'], ['chars', '字表'], ['char', '单字'], ['groups', '异体组']] as [Tab, string][]).map(([k, t]) => (
          <button key={k} className={tab === k ? 'active' : ''} onClick={() => set({ tab: k })}>{t}</button>
        ))}
      </div>
      {tab === 'summary' && <LibSummaryPanel onFilter={(f) => set({ tab: 'chars', f })} />}
      {tab === 'chars' && <LibCharTable filter={filter} setFilter={(f) => set({ f })} onPick={(c) => set({ tab: 'char', c })} />}
      {tab === 'char' && <LibCharDetail key={char} char={char} onPick={(c) => set({ c })} />}
      {tab === 'groups' && <GroupsTab />}
    </div>
  )
}

function GroupsTab() {
  const [books, setBooks] = useState<Book[]>([])
  const [book, setBook] = useState('')
  useEffect(() => {
    listBooks().then((bs) => { setBooks(bs); if (bs[0]) setBook(bs[0].id) }).catch(() => {})
  }, [])
  return (
    <div>
      <div className="card">
        <label className="muted">册
          <select value={book} onChange={(e) => setBook(e.target.value)}>
            {books.map((b) => <option key={b.id} value={b.id}>{b.id} · {b.title}</option>)}
          </select>
        </label>
        <span className="muted"> 异体组视图：按页跑一次任务后才有内容</span>
      </div>
      {book && <GroupsPanel book={book} />}
    </div>
  )
}
