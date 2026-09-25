import { useEffect, useMemo, useState } from 'react'
import { fetchLibChars, type LibChar } from '../../api/glyphlib'

// 字表：一字一格。过滤/排序全在前端（两本书都只有几千字）。
// 过滤键与总账页的可点数字对应：single / nofont / shared:<ws>。

const FILTERS: [string, string][] = [
  ['all', '全部'], ['single', '单例字'], ['nohuman', '无人裁'], ['humanonly', '只有人裁'],
  ['context', '含上下文放行'], ['nofont', '不在字体里'], ['unique', '本书独有'],
]

function pass(r: LibChar, f: string): boolean {
  switch (f) {
    case 'single': return r.n === 1
    case 'nohuman': return !r.prov.human
    case 'humanonly': return !!r.prov.human && Object.keys(r.prov).length === 1
    case 'context': return !!r.prov.context
    case 'nofont': return r.in_font === false
    case 'unique': return r.also_in.length === 0
    default:
      if (f.startsWith('shared:')) return r.also_in.includes(f.slice(7))
      return true
  }
}

export function LibCharTable({ filter, setFilter, onPick }: {
  filter: string; setFilter: (f: string) => void; onPick: (c: string) => void
}) {
  const [rows, setRows] = useState<LibChar[] | null>(null)
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<'n' | 'n-asc' | 'cp'>('n')
  const [limit, setLimit] = useState(600)
  useEffect(() => { fetchLibChars().then((d) => setRows(d.chars)).catch((e) => setErr((e as Error).message)) }, [])

  const others = useMemo(() => [...new Set((rows ?? []).flatMap((r) => r.also_in))], [rows])
  const shown = useMemo(() => {
    if (!rows) return []
    const qs = new Set([...q.trim()])
    const out = rows.filter((r) => pass(r, filter) && (qs.size === 0 || qs.has(r.char)))
    if (sort === 'n-asc') out.sort((a, b) => a.n - b.n || a.char.localeCompare(b.char))
    else if (sort === 'cp') out.sort((a, b) => (a.cp ?? 0) - (b.cp ?? 0))
    return out
  }, [rows, filter, q, sort])

  if (err) return <p className="error">{err}</p>
  if (!rows) return <p className="muted">读取中…</p>
  return (
    <div>
      <div className="pv-toolbar">
        <label className="muted">过滤
          <select value={filter} onChange={(e) => { setFilter(e.target.value); setLimit(600) }}>
            {FILTERS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            {others.map((w) => <option key={w} value={`shared:${w}`}>与 {w} 共有</option>)}
          </select>
        </label>
        <label className="muted">排序
          <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="n">刻例多→少</option><option value="n-asc">刻例少→多</option><option value="cp">码位</option>
          </select>
        </label>
        <label className="muted">查字 <input type="text" value={q} placeholder="粘一段字" onChange={(e) => setQ(e.target.value)} /></label>
        <span className="muted">{shown.length.toLocaleString()} / {rows.length.toLocaleString()} 字</span>
      </div>
      <div className="gl-grid">
        {shown.slice(0, limit).map((r) => (
          <button key={r.char} className={`gl-cell${r.prov.human ? ' gl-has-human' : ''}${r.in_font === false ? ' gl-nofont' : ''}`}
            title={title(r)} onClick={() => onPick(r.char)}>
            <span className="gl-ch">{r.char}</span>
            <span className="gl-n">{r.n}</span>
          </button>
        ))}
      </div>
      {shown.length > limit && <button onClick={() => setLimit(limit + 1200)}>再显示 1200 个</button>}
      <p className="muted gl-note">格右下是刻例数（按格去重）。左边竖条 = 有人裁；虚线框 = 字体里没有这个字。</p>
    </div>
  )
}

function title(r: LibChar) {
  const p = Object.entries(r.prov).map(([k, v]) => `${k} ${v}`).join(' · ')
  return `${r.char} U+${(r.cp ?? 0).toString(16).toUpperCase()}　${r.n} 例　${p}` +
    (r.semantic !== r.char ? `　读作 ${r.semantic}` : '') + (r.also_in.length ? `　也见于 ${r.also_in.join('、')}` : '')
}
