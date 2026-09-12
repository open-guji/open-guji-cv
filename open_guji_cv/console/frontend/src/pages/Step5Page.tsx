import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { STEP5_SUBS } from '../steps'
import { RarePanel } from '../components/rare/RarePanel'
import { fetchAlignRefSummary, fetchOcrCandidatesSummary } from '../api/products'
import type { AlignRefSummary, OcrCandidatesSummary } from '../api/products'
import { PageRangeSelector, loadSavedPageRange } from '../components/common/PageRangeSelector'
import { ProgressGatePanel } from '../components/common/ProgressGatePanel'

const ALIGN_REF_STEP_ID = 'step5-align-ref'
const OCR_CANDIDATES_STEP_ID = 'step5-ocr-candidates'

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

  if (sub === 'ocr') {
    return <OcrCandidatesPanel book={book} />
  }

  return (
    <div className="card">
      <h2>{meta?.title ?? sub}</h2>
      <p className="muted">{book} · 这一路的可视化还没有搬进来（v2 骨架阶段）。</p>
    </div>
  )
}

// Step5-c OCR 候选：07号任务卡判断这一路平时自动跑、大概率不需要独立
// 查询页（OCR 候选没有「人查某个字位」的场景，Step7 定字卡片已能看
// top-2）——本任务书（2026-09-11）核实这个判断仍成立（`ocr_candidates.py`
// 是逐字全自动产出，见 steps/ocr_candidates.py 模块头），所以不建单点
// 查询接口/页面，只做板块②聚合数字：引擎在线状态 + 候选覆盖率。
//
// 五点结构核对：①页面选择器 已加；②进度摘要 本组件本体；③待裁决 无
// （OCR 候选不是人裁的候选池，裁决在 Step7）；④产物 复用现成的
// ProductViewer 展示 ocr_candidates 逐页 JSON 即可，本次先不接（同 5-d，
// 属于「缺口小顺手做」以外的范围，留给以后）；⑤标注 无。
function OcrCandidatesPanel({ book }: { book: string }) {
  const [pageSel, setPageSel] = useState(() => loadSavedPageRange(OCR_CANDIDATES_STEP_ID, book))
  const [summary, setSummary] = useState<OcrCandidatesSummary | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setPageSel(loadSavedPageRange(OCR_CANDIDATES_STEP_ID, book))
  }, [book])

  useEffect(() => {
    setSummary(null)
    setErr('')
    if (!book) return
    fetchOcrCandidatesSummary(book, pageSel).then(setSummary).catch((e) => setErr((e as Error).message))
  }, [book, pageSel])

  const metrics = summary ? [
    { label: '引擎状态', value: summary.n_unavailable > 0
        ? `${summary.n_unavailable}/${summary.n_pages} 页引擎不在线`
        : Object.entries(summary.engines).map(([e, n]) => `${e} ×${n}`).join(' ') || '无产物',
      tone: (summary.n_unavailable > 0 ? 'bad' : 'ok') as 'bad' | 'ok' },
    { label: '候选覆盖率',
      value: summary.coverage == null ? '—' : `${(summary.coverage * 100).toFixed(2)}%（${summary.n_with_candidates}/${summary.n_chars}）`,
      tone: (summary.coverage != null && summary.coverage < 0.9 ? 'bad' : 'ok') as 'bad' | 'ok' },
    { label: '缺产物页数', value: String(summary.n_missing), tone: (summary.n_missing > 0 ? 'bad' : 'ok') as 'bad' | 'ok' },
  ] : undefined

  return (
    <div>
      <PageRangeSelector book={book} stepId={OCR_CANDIDATES_STEP_ID} value={pageSel} onChange={setPageSel} />
      {err && <div className="card"><p className="muted">{err}</p></div>}
      {!err && (
        <ProgressGatePanel
          book={book}
          title="Step5-c OCR 候选 —— 逐字全自动产出，无需单点查询（07号任务卡结论核实仍成立）"
          customMetrics={metrics}
        />
      )}
    </div>
  )
}

// Step5-d 整理本对齐：逐页锚定情况汇总，未锚定页带判据明细（n_grams/
// n_votes/vote_frac/dominance）——见 steps/align_ref.py::align_ref_summary
// 模块头「2026-09-11」一节，不用再临时写脚本复算卡在票数还是占比/优势上。
//
// 五点结构核对（03-Step页面统一设计.md §三）：
// ①页面选择器：2026-09-11 补，接 PageRangeSelector，串到 fetchAlignRefSummary
//   的 pages 参数（后端 api_align_ref_summary 已支持，此前前端没传）。
// ②进度摘要：锚定成功/失败/缺产物三态计数，已有，本次不改样式。
// ③待裁决：未锚定页 8-gram 判据明细，已有。
// ④产物：对勘报告（collation_vol01/02.html）在 overview 报告目录，不在本项目
//   静态资源里，控制台后端也没有服务它的路由——接链接需要新增静态文件服务，
//   超出「展示层核对」范围，这次不做，留给以后需要时再补（07号任务卡已有此结论）。
// ⑤标注：align_ref 不产生需要人工标注的候选（对齐正确与否由 8-gram 判据自动
//   给出，不是人裁的候选池），此路无此板块，不是漏做。
function AlignRefPanel({ book }: { book: string }) {
  const [pageSel, setPageSel] = useState(() => loadSavedPageRange(ALIGN_REF_STEP_ID, book))
  const [summary, setSummary] = useState<AlignRefSummary | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setPageSel(loadSavedPageRange(ALIGN_REF_STEP_ID, book))
  }, [book])

  useEffect(() => {
    setSummary(null)
    setErr('')
    if (!book) return
    fetchAlignRefSummary(book, pageSel).then(setSummary).catch((e) => setErr((e as Error).message))
  }, [book, pageSel])

  return (
    <div>
      <PageRangeSelector book={book} stepId={ALIGN_REF_STEP_ID} value={pageSel} onChange={setPageSel} />
      <div className="card">
        <h2>Step5-d 整理本对齐 <span className="muted">四路证据里的文本那一路，不拦截、只报可用性</span></h2>
        {err && <p className="muted">{err}</p>}
        {!err && !summary && <p className="muted">加载中…</p>}
        {summary && (
          <>
            <div className="counts" style={{ marginBottom: '.6rem' }}>
              <span className="s-fresh">锚定成功 {summary.n_anchored}/{summary.n_pages}</span>
              <span className="muted">锚定失败 {summary.n_not_anchored}</span>
              <span className="muted">缺产物 {summary.n_missing}</span>
            </div>
            {summary.pages.filter((p) => p.status === 'not_anchored').length > 0 && (
              <div className="mono" style={{ fontSize: '.8rem' }}>
                未锚定页（{summary.pages.filter((p) => p.status === 'not_anchored').length} 页）——8-gram 投票判据明细：
                {summary.pages.filter((p) => p.status === 'not_anchored').map((p) => (
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
          </>
        )}
      </div>
    </div>
  )
}
