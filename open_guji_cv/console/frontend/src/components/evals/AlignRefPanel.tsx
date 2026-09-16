import { useState } from 'react'
import { fetchAlignRefSummary } from '../../api/evals'
import type { AlignRefSummaryResponse } from '../../types/evals'

function pct(x: number) { return (x * 100).toFixed(1) + '%' }

// Step5-d 整理本匹配的锚定统计——不是闸（四路证据任一路缺席只降级不阻塞，
// 见 Step5 README），是"证据可用性上报"。原先要临时写脚本复算才知道哪页
// 锚不上、卡在哪条判据（票数/占比/优势），现在一条 API 直接列出来。
export function AlignRefPanel({ book }: { book: string }) {
  const [d, setD] = useState<AlignRefSummaryResponse | null>(null)
  const [msg, setMsg] = useState('')

  async function load() {
    setMsg('统计中…')
    try {
      setD(await fetchAlignRefSummary(book))
      setMsg('')
    } catch (e) {
      setD(null)
      setMsg('统计失败：' + (e as Error).message)
    }
  }

  const failed = d ? d.pages.filter((p) => p.status === 'not_anchored') : []

  return (
    <div className="card">
      <h2>整理本锚定 <span className="muted">Step5-d，四路证据之一，缺席只降级不阻塞</span>
        <button onClick={load} style={{ float: 'right' }}>统计</button></h2>
      {!d && <div className="muted">{msg || '点「统计」——列出全书哪些页锚不上、卡在哪条判据'}</div>}
      {d && (
        <div className="qgrid">
          <div>
            <div className="qk">锚定率</div>
            <div className={`qv ${d.n_not_anchored ? '' : 'qok'}`}>{pct(d.n_anchored / Math.max(1, d.n_pages))}</div>
            <div className="qs">锚定 {d.n_anchored} · 未锚定 {d.n_not_anchored} · 无产物 {d.n_missing} · 共 {d.n_pages} 页</div>
          </div>
          <div>
            <div className="qk">未锚定原因（判据明细）</div>
            {failed.length === 0 ? (
              <div className="qok" style={{ fontSize: '.78rem', marginTop: '.4rem' }}>全部锚上</div>
            ) : (
              <table className="jobs">
                <thead><tr><th>页</th><th>n_grams</th><th>vote_frac</th><th>dominance</th><th>原因</th></tr></thead>
                <tbody>
                  {failed.slice(0, 12).map((p) => (
                    <tr key={p.page}>
                      <td className="mono">p{p.page}</td>
                      <td className="mono">{p.n_grams}</td>
                      <td className="mono">{p.vote_frac?.toFixed(3)}</td>
                      <td className="mono">{p.dominance == null ? '—' : p.dominance.toFixed(2)}</td>
                      <td className="qs">{p.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {failed.length > 12 && <div className="qs">…另 {failed.length - 12} 页</div>}
            <div className="qs" style={{ marginTop: '.5rem' }}>
              锚定失败常见于书目提要类卷：格式化套话在全书重复出现，8-gram 窗口
              容易在别的条目里撞出票数更高的假峰（vote_frac 需 ≥0.15，dominance
              需 ≥2.0，两者任一不满足即判失败）。
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
