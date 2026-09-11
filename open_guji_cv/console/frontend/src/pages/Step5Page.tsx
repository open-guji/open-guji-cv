import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { STEP5_SUBS } from '../steps'
import { RarePanel } from '../components/rare/RarePanel'
import { fetchAlignRefSummary } from '../api/products'
import type { AlignRefSummary } from '../api/products'

// Step5 分四小步，路由 /<book>/step/step5/<sub>/，见方案 §二。
// D7：生僻字候选（rare.py，原本嵌在定字卡片里）独立成 5-b 的可视化。
// 5-d（整理本对齐）2026-09-11 接入锚定汇总面板。5-a/5-c 仍是骨架。
export function Step5Page() {
  const { book = '', sub } = useParams()
  const meta = sub ? STEP5_SUBS.find((s) => s.id === sub) : undefined

  if (!sub) {
    return (
      <div className="card">
        <h2>Step5 字符识别</h2>
        <p className="muted">四路并行，互不投票（流程与模块.md §4）：</p>
        <ul>
          {STEP5_SUBS.map((s) => (
            <li key={s.id}><Link to={`/${book}/step/step5/${s.id}/`}>{s.title}</Link></li>
          ))}
        </ul>
      </div>
    )
  }

  if (sub === 'rare') {
    return <RarePanel book={book} />
  }

  if (sub === 'align-ref') {
    return <AlignRefPanel book={book} />
  }

  return (
    <div className="card">
      <h2>{meta?.title ?? sub}</h2>
      <p className="muted">{book} · 这一路的可视化还没有搬进来（v2 骨架阶段）。</p>
    </div>
  )
}

// Step5-d 整理本对齐：逐页锚定情况汇总，未锚定页带判据明细（n_grams/
// n_votes/vote_frac/dominance）——见 steps/align_ref.py::align_ref_summary
// 模块头「2026-09-11」一节，不用再临时写脚本复算卡在票数还是占比/优势上。
// 风格仿 Step2Page 的 GateSummaryPanel，但 align_ref 不是闸、没有 tier
// 分层配色——只有「锚定成功/失败/缺产物」三态。
function AlignRefPanel({ book }: { book: string }) {
  const [summary, setSummary] = useState<AlignRefSummary | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setSummary(null)
    setErr('')
    if (!book) return
    fetchAlignRefSummary(book).then(setSummary).catch((e) => setErr((e as Error).message))
  }, [book])

  if (err) return <div className="card"><p className="muted">{err}</p></div>
  if (!summary) return <div className="card"><p className="muted">加载中…</p></div>

  const failed = summary.pages.filter((p) => p.status === 'not_anchored')

  return (
    <div className="card">
      <h2>Step5-d 整理本对齐 <span className="muted">四路证据里的文本那一路，不拦截、只报可用性</span></h2>
      <div className="counts" style={{ marginBottom: '.6rem' }}>
        <span className="s-fresh">锚定成功 {summary.n_anchored}/{summary.n_pages}</span>
        <span className="muted">锚定失败 {summary.n_not_anchored}</span>
        <span className="muted">缺产物 {summary.n_missing}</span>
      </div>
      {failed.length > 0 && (
        <div className="mono" style={{ fontSize: '.8rem' }}>
          未锚定页（{failed.length} 页）——8-gram 投票判据明细：
          {failed.map((p) => (
            <div key={p.page} className="preclean-report-rule">
              第 {p.page} 页：{p.note}
              {p.n_grams ? (
                <span className="muted">
                  {' '}（n_grams={p.n_grams} n_votes={p.n_votes} vote_frac={p.vote_frac?.toFixed(3)}
                  {' '}dominance={p.dominance == null ? '∞' : p.dominance.toFixed(2)}）
                </span>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
