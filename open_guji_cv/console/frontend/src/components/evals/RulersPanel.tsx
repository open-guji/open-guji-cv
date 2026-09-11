import { useState } from 'react'
import { fetchRulers } from '../../api/evals'
import type { RulerRow } from '../../types/evals'

// 迁移自 v1 health.js::loadRulers。四把尺子：Step 1-4 离 100% 还差什么。
export function RulersPanel({ book }: { book: string }) {
  const [rows, setRows] = useState<RulerRow[] | null>(null)
  const [msg, setMsg] = useState('')

  async function load() {
    setMsg('测量中…（要读列图，十几秒）')
    try {
      const d = await fetchRulers(book, 'dev_set')
      setRows(d.rulers)
      setMsg('')
    } catch (e) {
      setMsg('测量失败：' + (e as Error).message)
    }
  }

  return (
    <div className="card">
      <h2>四把尺子 <span className="muted">Step 1-4 离 100% 还差什么</span>
        <button onClick={load} style={{ float: 'right' }}>测量</button></h2>
      {!rows && <div className="muted">{msg || '点「测量」跑（dev_set 约需十几秒）'}</div>}
      {rows && (
        <>
          <table className="jobs">
            <thead><tr><th>#</th><th>尺子</th><th>现值</th><th>分子/分母</th><th>目标</th><th>头几条（可点页去看）</th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const v = r.value == null ? '—' : r.value.toFixed(2) + r.unit
                const good = r.goal === '0' ? r.num === 0 : (r.goal === '100%' ? r.num === r.den : null)
                const cls = good === null ? '' : (good ? 'qok' : 'qbad')
                const det = (r.detail || []).slice(0, 6).map((x) =>
                  `p${x.page}${x.col != null ? ` c${x.col}` : ''}${x.slot != null ? ` s${x.slot}` : ''}${x.px != null ? ` ${x.px}px` : ''}`,
                ).join(' · ')
                return (
                  <tr key={r.key}>
                    <td className="mono">{r.key}</td>
                    <td>{r.title}<div className="qs">{r.note}</div></td>
                    <td className={`mono ${cls}`}>{v}</td>
                    <td className="mono qs">{r.num}/{r.den}</td>
                    <td className="qs">{r.goal}</td>
                    <td className="qs">{det}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="qs ruler-note">
            <b>怎么读</b>：R2「真粘连」是图像极限（笔画物理相连），
            标 flag 交人审即可，<b>不算错</b>；要盯的是「可改善」。
            R4 只认紧贴紧框的笔画级墨段——窗口若开到版框会扫进邻字，
            把整字高度（~110px）误报成被切。
          </div>
        </>
      )}
    </div>
  )
}
