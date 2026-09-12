import { useState } from 'react'
import { fetchGateSummary, GATE_IDS } from '../../api/evals'
import type { GateSummaryResponse } from '../../types/evals'

const GATE_LABEL: Record<string, string> = {
  column_gate: '闸2 · 单列射影出口',
  row_segment_gate: '闸3 · 逐字切分出口',
  border_detect_gate: '闸1 · 边框界行出口',
}

// 三道闸（截至 2026-09-11 只落地这三道，见交接闸 README）的过闸/拦截统计。
// `gates/query.py::gate_summary` 的前端呈现——原先只有命令行能查，
// vol01 p90-132 那类"整页被拦、没人跟踪"的情况现在能在这里直接看到。
export function GateSummaryPanel({ book }: { book: string }) {
  const [gate, setGate] = useState<string>('column_gate')
  const [d, setD] = useState<GateSummaryResponse | null>(null)
  const [msg, setMsg] = useState('')

  async function load(g: string) {
    setGate(g)
    setMsg('统计中…')
    try {
      setD(await fetchGateSummary(book, g))
      setMsg('')
    } catch (e) {
      setD(null)
      setMsg('统计失败：' + (e as Error).message)
    }
  }

  const blocked = d ? d.pages.filter((p) => p.status === 'page_blocked') : []
  const missing = d ? d.pages.filter((p) => p.status === 'missing') : []
  const ok = d ? d.pages.filter((p) => p.status === 'ok') : []

  return (
    <div className="card">
      <h2>交接闸 <span className="muted">已落地的 {GATE_IDS.length} 道闸，逐页过闸/拦截统计</span></h2>
      <div className="evals-toolbar">
        {GATE_IDS.map((g) => (
          <button key={g} className={g === gate ? '' : 'ghost'} onClick={() => load(g)}>{GATE_LABEL[g]}</button>
        ))}
        <span className="muted">{msg}</span>
      </div>
      {!d && <div className="muted">点上面任一道闸查看统计</div>}
      {d && (
        <div className="qgrid">
          <div>
            <div className="qk">页级状态</div>
            <div className={`qv ${blocked.length ? 'qbad' : 'qok'}`}>{ok.length}/{d.pages.length}</div>
            <div className="qs">过闸 {ok.length} · 整页被拦 {blocked.length} · 无产物 {missing.length}</div>
            {blocked.length > 0 && (
              <div className="qerr">
                {blocked.slice(0, 8).map((p) => (
                  <div key={p.page}>p{p.page}：{(p.page_reject || []).join('；')}</div>
                ))}
                {blocked.length > 8 && <div className="qs">…另 {blocked.length - 8} 页，见命令行 `gates.query`</div>}
              </div>
            )}
          </div>
          <div>
            <div className="qk">拒因分层（列级）</div>
            {Object.keys(d.tier_totals).length === 0 ? (
              <div className="qok" style={{ fontSize: '.78rem', marginTop: '.4rem' }}>零列被拦</div>
            ) : (
              <table className="jobs">
                <tbody>
                  {Object.entries(d.tier_totals).sort((a, b) => b[1] - a[1]).map(([tier, n]) => (
                    <tr key={tier}><td className="mono">{tier}</td><td className="mono">{n}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="qs" style={{ marginTop: '.5rem' }}>
              L1/L1c 是几何硬约束（列数/列宽），L2 是信号判据（侧边墨量），
              L3 是人裁金标——分层从便宜到贵，见交接闸 README。
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
