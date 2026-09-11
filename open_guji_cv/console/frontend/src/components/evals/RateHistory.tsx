import { useEffect, useState } from 'react'
import { fetchRateHistory, postRateSnapshot } from '../../api/evals'
import type { RateHistoryRow } from '../../api/evals'

// 迁移自 v1 health.js::loadRateHistory。判据 B 行下面的趋势条。
export function RateHistory({ book }: { book: string }) {
  const [rows, setRows] = useState<RateHistoryRow[] | null>(null)
  const [error, setError] = useState('')
  const [snapping, setSnapping] = useState(false)

  async function load() {
    try {
      setRows((await fetchRateHistory(book)).rows || [])
    } catch (e) {
      setError('台账读不出来：' + (e as Error).message)
    }
  }

  useEffect(() => { load() }, [book]) // eslint-disable-line react-hooks/exhaustive-deps

  async function snap() {
    setSnapping(true)
    try {
      await postRateSnapshot(book, window.prompt('这次的说明（可留空）') || '')
      await load()
    } catch {
      setError('记一笔失败')
    } finally {
      setSnapping(false)
    }
  }

  const snapBtn = <button className="mini" disabled={snapping} onClick={snap}>{snapping ? '记录中…' : '记一笔'}</button>

  if (error) return <div className="qs">{error}</div>
  if (!rows) return <div className="qs">台账载入中…</div>
  if (!rows.length) return <div className="qs">台账还没有 {book} 的记录 {snapBtn}</div>

  const first = rows[0]
  const last = rows[rows.length - 1]
  const max = Math.max(...rows.map((r) => r.rate))

  return (
    <div className="qs">
      <b>台账</b> {first.date} <b>{(first.rate * 100).toFixed(2)}%</b>
      {' → 今 '}<b>{(last.rate * 100).toFixed(2)}%</b>
      （降 {((1 - last.rate / Math.max(first.rate, 1e-9)) * 100).toFixed(0)}%，{rows.length} 次记录）
      {last.unseen_rate != null && <>　未审段 <b>{(last.unseen_rate * 100).toFixed(2)}%</b></>}
      <span className="rbars">
        {rows.map((r, i) => (
          <span key={i} className="rbar" style={{ height: Math.max(2, Math.round((r.rate / max) * 22)) }}
                title={`${r.date} ${(r.rate * 100).toFixed(2)}%${r.unseen_rate != null ? `　未审段 ${(r.unseen_rate * 100).toFixed(2)}%` : ''}\n${r.note || ''}`} />
        ))}
      </span>
      {' '}{snapBtn}
    </div>
  )
}
