import { useState } from 'react'
import { fetchQuality } from '../../api/evals'
import type { QualityResponse } from '../../api/evals'

// 迁移自 v1 health.js::loadQuality。裁完先看这里：准了没有、下一刀切哪。
export function QualityPanel({ book, pages }: { book: string; pages: string }) {
  const [d, setD] = useState<QualityResponse | null>(null)
  const [msg, setMsg] = useState('')

  async function load() {
    setMsg('统计中…')
    try {
      setD(await fetchQuality(book, pages || 'dev_set'))
      setMsg('')
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  const pct = (x: number | null | undefined) => x == null ? '—' : `${(x * 100).toFixed(2)}%`
  const chips = (rows: Array<{ key: string; n: number }>) => rows.map((r, i) => (
    <span className="qchip" key={i}>{r.key}<b>{r.n}</b></span>
  ))

  return (
    <div className="card">
      <h2>质量看板 <span className="muted">裁完先看这里：准了没有、下一刀切哪</span>
        <button onClick={load} style={{ float: 'right' }}>刷新</button></h2>
      {!d && <div className="muted">{msg || '点「刷新」载入'}</div>}
      {d && (
        <div className="qgrid">
          <div>
            <div className="qk">定字准确率</div>
            <div className={`qv ${d.accuracy.overall === 1 ? 'qok' : 'qbad'}`}>{pct(d.accuracy.overall)}</div>
            <div className="qs">对整理本自动金标 {d.accuracy.n_gold} 条（覆盖 {pct(d.accuracy.gold_coverage)} 的字位）</div>
            <table className="jobs" style={{ marginTop: '.4rem' }}>
              <tbody>
                {d.accuracy.by_channel.map((c, i) => (
                  <tr key={i}>
                    <td>{c.channel}</td>
                    <td className="mono">{c.ok}/{c.n}</td>
                    <td className={`mono ${c.acc < 1 ? 'qbad' : 'qok'}`}>{pct(c.acc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {d.accuracy.errors.length ? (
              <div className="qerr">错例：{d.accuracy.errors.slice(0, 8).map((e, i) => (
                <span key={i} className="mono">{i > 0 && ' · '}{e.id} 判「{e.pred}」金标「{e.gold}」({e.channel})</span>
              ))}</div>
            ) : <div className="qok" style={{ fontSize: '.78rem', marginTop: '.4rem' }}>金标覆盖范围内零错例</div>}
          </div>
          <div>
            <div className="qk">人裁标出的切分缺陷 <b>{d.defects.n}</b> 条</div>
            <div className="qs" style={{ margin: '.3rem 0' }}>类型 {chips(d.defects.by_quality)}</div>
            <div className="qs">缺陷细类 {chips(d.defects.by_defect)}</div>
            <div className="qs">按页 {chips(d.defects.by_page)}</div>
            <div className="qs">按列 {chips(d.defects.by_col)}</div>
            <div className="qs">按格位 {chips(d.defects.by_slot)}</div>
            <div className="qs" style={{ marginTop: '.5rem', lineHeight: 1.7 }}>
              <b>怎么读</b>：孤例是个案，<b>扎堆才是系统性问题</b>。某个格位反复出问题
              → 那一格的先验或边界有系统偏差；某一页占了大半 → 先查那页的上游几何。
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
