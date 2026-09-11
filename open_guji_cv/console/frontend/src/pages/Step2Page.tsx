import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchGateSummary } from '../api/products'
import { ProductViewer } from '../components/ProductViewer'
import { usePages } from '../hooks/usePages'
import type { GateSummary } from '../api/products'

// 闸2（column_gate）分层配色，与后端 gates/query.py::GATE_TIER_COLOR 对齐
// （BGR→CSS 顺手换算，颜色本身以后端为准，这里只是给人看的图例）。
const TIER_LABEL: Record<string, string> = {
  L1: '整页列数不对', L1c: '列宽偏离中位数（多半圈进界行）',
  L2: '两侧外沿墨占比超界', L3: '人裁金标（P2 未接，不生效）',
}
const TIER_COLOR: Record<string, string> = {
  L1: '#dc0000', L1c: '#ff8c00', L2: '#00b8b8', L3: '#b400b4',
}

function GateSummaryPanel({ book }: { book: string }) {
  const [summary, setSummary] = useState<GateSummary | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setSummary(null)
    setErr('')
    if (!book) return
    fetchGateSummary(book).then(setSummary).catch((e) => setErr((e as Error).message))
  }, [book])

  if (err) return <div className="card"><p className="muted">{err}</p></div>
  if (!summary) return <div className="card"><p className="muted">加载中…</p></div>

  const known = summary.pages.filter((p) => p.status !== 'missing')
  const totalCols = known.reduce((s, p) => s + (p.n_columns ?? 0), 0)
  const admittedCols = known.reduce((s, p) => s + (p.n_admitted ?? 0), 0)
  const blockedPages = known.filter((p) => p.status === 'page_blocked')

  return (
    <div className="card">
      <h2>闸2（Step2→3 交接闸）<span className="muted">L1 页级 / L1c、L2 列级；L3 尚未接入</span></h2>
      <div className="counts" style={{ marginBottom: '.6rem' }}>
        <span className="muted">{known.length} 页有闸产物（{summary.pages.length - known.length} 页缺产物）</span>
        <span className="s-fresh">列过闸 {admittedCols}/{totalCols}</span>
        {Object.entries(summary.tier_totals).map(([tier, n]) => (
          <span key={tier} style={{ background: `${TIER_COLOR[tier]}22`, color: TIER_COLOR[tier] }}>
            {tier} 拦 {n} 列
          </span>
        ))}
      </div>
      <div className="counts" style={{ marginBottom: '.6rem' }}>
        {Object.entries(TIER_LABEL).map(([tier, label]) => (
          <span key={tier} className="muted">
            <b style={{ color: TIER_COLOR[tier] }}>{tier}</b> {label}
          </span>
        ))}
      </div>
      {blockedPages.length > 0 && (
        <div className="mono" style={{ fontSize: '.8rem' }}>
          整页未过 L1（{blockedPages.length} 页）：
          {blockedPages.map((p) => (
            <div key={p.page} className="preclean-report-rule">
              第 {p.page} 页：{(p.page_reject ?? []).join('；')}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Step2 单列射影 + 闸2 可视化（overview 2026-09-11 下发，正本
// 项目进展/图片初步数字化/进度/Step2-单列射影/03-控制台可视化.md）。
// 闸2 的 L1/L1c/L2 都有现成产物，直接汇总展示；L3 人裁金标目前只是代码占位
// （tier=gate 时不生效，见 gates/column_gate.py），不当作已实现来做界面。
export function Step2Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)
  return (
    <div>
      <GateSummaryPanel book={book} />
      <ProductViewer book={book} step="column_gate" pages={pages} />
    </div>
  )
}
