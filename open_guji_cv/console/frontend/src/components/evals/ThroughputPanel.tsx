import { useState } from 'react'
import { fetchThroughput } from '../../api/evals'
import type { ThroughputResponse } from '../../types/evals'

const STEP_LABEL: Record<string, string> = {
  preclean: '预清理', border_detect: '边框界行', column_warp: '单列射影',
  row_segment: '逐字切分', cell_shrink: '字框收缩', glyph_match: '库匹配',
  ocr_candidates: 'OCR候选', align_ref: '整理本匹配', context_decide: '上下文裁决',
  seed_admit: '放行判定',
}

const CHAN_LABEL_MAX = 6

function pct(x: number) { return (x * 100).toFixed(1) + '%' }
function secs(x: number) { return x < 1 ? Math.round(x * 1000) + 'ms' : x.toFixed(2) + 's' }

// 逐页人审率：跟 RateHistory 一样走 CSS 竖条 sparkline，不上 SVG——
// 这是控制台里的一个面板，不是独立发布页，视觉克制优先。
function PageSparkline({ pages }: { pages: ThroughputResponse['per_page']['pages'] }) {
  const valid = pages.filter((p) => p.n_total > 0)
  if (!valid.length) return <div className="qs">这册还没有产物</div>
  const max = Math.max(0.02, ...valid.map((p) => p.review_rate || 0))
  return (
    <div className="qs">
      <span className="rbars" style={{ height: 28 }}>
        {valid.map((p, i) => (
          <span key={i} className="rbar"
                style={{ height: Math.max(2, Math.round(((p.review_rate || 0) / max) * 26)) }}
                title={`p${p.page}　人审率 ${pct(p.review_rate || 0)}\n输入 ${p.n_total}　自动 ${p.n_auto}　人审 ${p.n_review}`} />
        ))}
      </span>
      <div className="qs">p{valid[0].page} → p{valid[valid.length - 1].page}，{valid.length} 页有产物（悬停查看单页数值）</div>
    </div>
  )
}

function ChannelBars({ channels, totalAuto }: { channels: ThroughputResponse['channels']['channels']; totalAuto: number }) {
  const sorted = [...channels].sort((a, b) => b.n - a.n)
  const head = sorted.slice(0, CHAN_LABEL_MAX)
  const tail = sorted.slice(CHAN_LABEL_MAX)
  const rows = tail.length
    ? [...head, { channel: `其它(${tail.length})`, n: tail.reduce((s, c) => s + c.n, 0), pct: tail.reduce((s, c) => s + c.pct, 0) }]
    : head
  const maxPct = rows[0]?.pct || 1
  return (
    <table className="jobs">
      <tbody>
        {rows.map((c) => (
          <tr key={c.channel}>
            <td className="mono qs" style={{ width: '9rem' }}>{c.channel}</td>
            <td style={{ width: '60%' }}>
              <div style={{ background: 'var(--paper)', borderRadius: 3, height: 12, overflow: 'hidden' }}>
                <div style={{ width: `${(c.pct / maxPct * 100).toFixed(1)}%`, height: '100%', background: 'var(--indigo)', opacity: .6 }} />
              </div>
            </td>
            <td className="mono qs" style={{ textAlign: 'right' }}>{pct(c.pct)}（{c.n}）</td>
          </tr>
        ))}
      </tbody>
      <tfoot><tr><td colSpan={3} className="qs">共 {totalAuto} 字位自动放行</td></tr></tfoot>
    </table>
  )
}

function TimingTable({ steps }: { steps: ThroughputResponse['timing']['steps'] }) {
  const withData = steps.filter((s) => s.n_pages > 0)
  const maxTotal = Math.max(...withData.map((s) => s.total_s || 0), 1)
  return (
    <table className="jobs">
      <thead><tr><th>Step</th><th>页数</th><th>中位/页</th><th>p90/页</th><th>合计</th></tr></thead>
      <tbody>
        {steps.map((s) => (
          <tr key={s.step}>
            <td>{STEP_LABEL[s.step] || s.step}</td>
            {s.n_pages ? (
              <>
                <td className="mono">{s.n_pages}</td>
                <td className="mono">{secs(s.median_s || 0)}</td>
                <td className="mono">{secs(s.p90_s || 0)}</td>
                <td className="mono" style={{ position: 'relative' }}>
                  <div style={{ position: 'absolute', inset: '2px 0', background: 'var(--paper)', borderRadius: 2, zIndex: 0 }} />
                  <div style={{ position: 'absolute', inset: '2px auto 2px 0', width: `${((s.total_s || 0) / maxTotal * 100).toFixed(1)}%`, background: 'var(--indigo)', opacity: .25, borderRadius: 2, zIndex: 0 }} />
                  <span style={{ position: 'relative' }}>{(s.total_s || 0) >= 60 ? ((s.total_s || 0) / 60).toFixed(1) + 'min' : (s.total_s || 0).toFixed(1) + 's'}</span>
                </td>
              </>
            ) : <td colSpan={4} className="muted">无产物记录</td>}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// 吞吐量三件套：逐页输入输出 / 自动放行通道占比 / 各步 performance。
// `eval/throughput.py` 的前端呈现——只读现有产物聚合，不重跑管线、不重新计时。
export function ThroughputPanel({ book }: { book: string }) {
  const [d, setD] = useState<ThroughputResponse | null>(null)
  const [msg, setMsg] = useState('')

  async function load() {
    setMsg('统计中…（读全书产物，几秒）')
    try {
      setD(await fetchThroughput(book))
      setMsg('')
    } catch (e) {
      setMsg('统计失败：' + (e as Error).message)
    }
  }

  return (
    <div className="card">
      <h2>吞吐量 <span className="muted">逐页输入输出 · 自动放行通道占比 · 各步 performance</span>
        <button onClick={load} style={{ float: 'right' }}>统计</button></h2>
      {!d && <div className="muted">{msg || '点「统计」——只读现有产物，不重新跑管线'}</div>}
      {d && (
        <div className="qgrid">
          <div>
            <div className="qk">逐页人审率</div>
            <PageSparkline pages={d.per_page.pages} />
          </div>
          <div>
            <div className="qk">自动放行通道占比</div>
            <ChannelBars channels={d.channels.channels} totalAuto={d.channels.total_auto} />
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div className="qk">各步 Performance</div>
            <TimingTable steps={d.timing.steps} />
          </div>
        </div>
      )}
    </div>
  )
}
