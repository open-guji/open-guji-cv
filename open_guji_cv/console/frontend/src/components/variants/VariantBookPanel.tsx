import { useState } from 'react'
import { fetchVariantBook } from '../../api/variants'
import type { VariantBookResponse, VariantGroup } from '../../types/variants'
import './variants.css'

// 迁移自 v1 static/js/panels/variants.js（57 行，只读账本）。
// 数据全部来自 /api/variants/book，页面不算账（真源是 scripts/build_book_variants.py）。
export function VariantBookPanel() {
  const [edition, setEdition] = useState('wuyingdian_zongmu')
  const [q, setQ] = useState('')
  const [data, setData] = useState<VariantBookResponse | null>(null)
  const [stat, setStat] = useState('')

  async function load() {
    setStat('读取中…')
    try {
      const d = await fetchVariantBook(edition.trim() || 'wuyingdian_zongmu')
      setData(d)
    } catch (e) {
      setStat((e as Error).message)
      setData(null)
    }
  }

  const carved = (g: VariantGroup, mm: string) => {
    const b = g.forms[mm].book
    return b.products + b.db - b.align
  }
  const weight = (g: VariantGroup) => {
    const pairSum = Object.values(g.pairs).reduce((a, p) => a + p.n, 0) * 10
    const memberSum = g.members
      .filter((mm) => mm !== g.canonical)
      .reduce((a, mm) => a + Math.max(0, carved(g, mm)), 0)
    return pairSum + memberSum
  }

  const m = data?.meta
  const s = m?.stats
  const inp = m?.inputs
  const statLine = data
    ? `${m?.edition} · 组 ${s?.groups}（整理本单形 ${s?.ref_single} / 多形 ${s?.ref_multi}）· 转换对 ${s?.pairs} · 关系图外 ${s?.unknown_pairs} · 产物 ${inp?.products_records} 条 / glyph.db ${inp?.glyph_db_instances} 例 · ${m?.built_at || ''}`
    : stat

  const rows = data
    ? Object.values(data.groups)
        .filter((g) => !q.trim() || [...q.trim()].some((ch) => g.members.includes(ch)))
        .sort((a, b) => weight(b) - weight(a) || a.canonical.localeCompare(b.canonical))
    : []

  const sub = (n: number, h?: number) => <sub>{n}{h ? `·人${h}` : ''}</sub>

  return (
    <div className="card">
      <h2>本书用字账 <span className="muted">这本书刻了哪些异体、整理本印成什么；只读，由 scripts/build_book_variants.py 派生</span></h2>
      <div className="var-row">
        <label>套 <input value={edition} onChange={(e) => setEdition(e.target.value)} size={18} /></label>
        <label>筛 <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="输入一个或几个字" size={14} /></label>
        <button onClick={load}>重新读取</button>
        <span className="muted">{statLine}</span>
      </div>
      <p className="muted var-help">
        计数读法：<b>刻本形</b>下标是本书刻了几次（products + glyph.db，扣掉 v1 整理本贴标的 align），「·人N」是其中人裁确认的；
        <b>整理本形</b>下标是整理本印了几次；<b>转换对</b>是自动或人裁把「刻本形→文意」记下的次数。
        整理本一栏：single = 整理本对这组只用一种形（它定义不定形，形只能来自图像）；multi = 整理本自己在区分（它的字兼作形证据）。
        分型是关系层的先验（T1 纯异体 / T2 互通·一对多 / T3 形近·通假·仅简繁），最终由这张账定。
      </p>
      {rows.length > 0 ? (
        <table className="jobs vtbl">
          <thead>
            <tr><th>组</th><th>刻本形</th><th>整理本形</th><th>转换对（刻本形→文意）</th><th>整理本</th><th>分型（先验）</th></tr>
          </thead>
          <tbody>
            {rows.map((g) => {
              const forms = g.members.map((mm) => {
                const n = carved(g, mm)
                if (n <= 0) return null
                return <span key={mm} className={mm === g.preferred ? 'vpref' : ''}>{mm}{sub(n, g.forms[mm].book.human)} </span>
              })
              const refs = g.members.map((mm) => (
                g.forms[mm].ref > 0 ? <span key={mm}>{mm}{sub(g.forms[mm].ref)} </span> : null
              ))
              const pairs = Object.entries(g.pairs).map(([k, v]) => <span key={k}>{k}{sub(v.n, v.human)} </span>)
              const tiers = g.members.filter((mm) => mm !== g.canonical).map((mm) => `${mm}:${g.forms[mm].tier || '—'}`).join(' ')
              return (
                <tr key={g.canonical}>
                  <td className="vgl">{g.canonical}</td>
                  <td>{forms.some(Boolean) ? forms : '—'}</td>
                  <td>{refs.some(Boolean) ? refs : '—'}</td>
                  <td>{pairs.length ? pairs : '—'}</td>
                  <td>{g.ref_policy}</td>
                  <td className="muted">{tiers}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : data ? <span className="muted">没有匹配的组</span> : null}
      {data && data.unknown_pairs.length > 0 && (
        <div className="muted var-unknown">
          关系图里没有这条边、或两头落在不同组的转换对（新异体 / OCR 错 / 整理本错 三选一，待审）：
          {data.unknown_pairs.map((u, i) => (
            <span key={i}>　{u.shape}→{u.reading}{sub(u.n, u.human)}</span>
          ))}
        </div>
      )}
    </div>
  )
}
