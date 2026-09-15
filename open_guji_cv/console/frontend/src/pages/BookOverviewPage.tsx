import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchStatus, setOcrCandidates } from '../api/status'
import { fetchOverviewSummary } from '../api/evals'
import { fetchLlmOnlineStats } from '../api/llmOnline'
import type { StatusResponse } from '../types/status'
import type { OverviewSummaryResponse } from '../types/evals'
import type { LlmOnlineStats } from '../api/llmOnline'
import { STEPS, backendIdFor } from '../steps'
import { getBook } from '../api/registry'
import type { Book } from '../types/registry'

// Step5「字符识别」在 steps.ts 里 backendIds 是空的（它是四小步的容器，没有单一
// 后端 step），于是总进度里整个 Step5 看不见——而 5-a/5-b/5-d 恰恰是全书跑得最
// 慢的三步。2026-09-13 补：总览页单独把它们展开成子行（5-c OCR 候选默认关闭，
// 只在本书启用时才显示）。这里不动 steps.ts 的 backendIds，因为 StepPage 拿
// backendIds[0] 当唯一后端步用，填上会让 Step5 页面错关联到 5-a。
const STEP5_ROWS: { id: string; title: string; backendId: string; optional?: boolean }[] = [
  { id: 'glyph-match', title: '　5-a 字形库匹配', backendId: 'glyph_match' },
  { id: 'rare', title: '　5-b 生僻字候选', backendId: 'rare_candidates' },
  { id: 'ocr', title: '　5-c OCR 候选', backendId: 'ocr_candidates', optional: true },
  { id: 'align-ref', title: '　5-d 整理本匹配', backendId: 'align_ref' },
]
import './overview.css'

// D2 → 2026-09-11 重构：用户反馈"总览完全没用、状态矩阵太乱"——原版第一个
// card 只是管线 DAG 图（纯节点名+箭头，零进度信息），第二个 card 是每步×
// 每页的巨型格子矩阵（vol01 就有 9 步 × 206 页 ≈ 1800 格，挤在一屏看不出
// 整体进度）。总览该回答的是三件事，不是"这本书的每一格产物长什么样"：
//   1. 总进度——每步走到哪了，一眼看出卡在哪一步（进度条，不是逐页格子）
//   2. 待办——下一批要跑/要审的页
//   3. 异常数据——闸拦了多少页、Step5-d 锚不上多少页、人审率是否正常
// 逐页细节（哪一页哪一步失败）不在总览页丢弃，去对应 Step 页面查——
// 状态矩阵组件本身还在，只是不再是总览页的主体。
//
// `/api/overview_summary` 是这次新加的轻量聚合接口：只读产物（人审率台账
// ~0.7s + 三道闸汇总 + align-ref 锚定，各 ~0.05s），不跑完整判据A-F体检
// （那要10+秒，判据D读CNN候选是耗时大户）——总览页一进来就等 10 秒不合理，
// 完整体检留给「统计数据」页手动点。
export function BookOverviewPage() {
  const { book = '' } = useParams()
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [devStatus, setDevStatus] = useState<StatusResponse | null>(null)
  const [summary, setSummary] = useState<OverviewSummaryResponse | null>(null)
  const [llmStats, setLlmStats] = useState<LlmOnlineStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocrBusy, setOcrBusy] = useState(false)
  const [ocrErr, setOcrErr] = useState<string | null>(null)
  const [bookMeta, setBookMeta] = useState<Book | null>(null)

  useEffect(() => {
    setStatus(null)
    setDevStatus(null)
    setSummary(null)
    setLlmStats(null)
    setError(null)
    setOcrErr(null)
    // 总进度是**全书**口径（`all`，vol01 为 206 页，实测 ~2.5s）。2026-09-13 修：
    // 此前不传 pages，走 fetchStatus 的默认 `dev_set`，只统计 12 页分层小集，
    // 标题却写「全书页数」——名实不符，看着像整本书跑完了，其实只跑了 12 页。
    // dev_set 那份仍单独取一份并列显示，调参时照样能一眼看到小集进度。
    setBookMeta(null)
    // 管线按册书取（2026-09-15）：写死刻本链时，现代印刷本的总进度条全是 0/80。
    getBook(book).then((b) => {
      setBookMeta(b ?? null)
      const pid = b?.pipeline || 'keben_body_v2'
      fetchStatus(book, pid, 'all').then(setStatus).catch((e) => setError(String(e)))
      fetchStatus(book, pid, 'dev_set').then(setDevStatus).catch(() => setDevStatus(null))
    }).catch(() => {
      fetchStatus(book, 'keben_body_v2', 'all').then(setStatus).catch((e) => setError(String(e)))
      fetchStatus(book, 'keben_body_v2', 'dev_set').then(setDevStatus).catch(() => setDevStatus(null))
    })
    fetchOverviewSummary(book).then(setSummary).catch((e) => setError(String(e)))
    fetchLlmOnlineStats(book).then(setLlmStats).catch(() => setLlmStats(null))
  }, [book])

  const total = status?.pages.length || 0
  const devTotal = devStatus?.pages.length || 0

  async function toggleOcrCandidates(next: boolean) {
    setOcrBusy(true)
    setOcrErr(null)
    try {
      await setOcrCandidates(book, next)
      setStatus((s) => (s ? { ...s, ocr_candidates_enabled: next } : s))
    } catch (e) {
      setOcrErr(String(e))
    } finally {
      setOcrBusy(false)
    }
  }

  return (
    <div>
      {error && <div className="card"><p className="error">{error}</p></div>}
      {status?.workspace?.is_sample_db && (
        <div className="card"><p className="error">⚠ 用的是仓内示例库（未设 GUJI_WORKSPACE）</p></div>
      )}

      <div className="card">
        <h2>{book} 总进度 <span className="muted">每步 fresh 产物 / 全书 {total || '…'} 页（括号内为 dev_set {devTotal || '…'} 页小集）</span></h2>
        {!status && !error && <p className="muted">加载中…（全书状态约需数秒）</p>}
        {status && STEPS.flatMap((s) => {
          // Step5 展开成 5-a/5-b/(5-c)/5-d 四条子行；其余步一步一行。
          if (s.id === 'step5') {
            return STEP5_ROWS
              .filter((r) => !r.optional || status.ocr_candidates_enabled)
              .map((r) => ({ key: `step5-${r.id}`, href: `/${book}/step/step5/${r.id}/`,
                             title: r.title, sid: r.backendId }))
          }
          const sid = backendIdFor(s, bookMeta?.edition)
          if (!sid) return []
          return [{ key: s.id, href: `/${book}/step/${s.id}/`, title: s.title, sid }]
        }).map((row) => {
          const d = status.steps[row.sid]
          if (!d) return null
          const fresh = d.counts.fresh
          const cls = fresh === 0 ? 'empty' : (fresh >= total ? 'full' : 'partial')
          const dev = devStatus?.steps[row.sid]?.counts.fresh
          return (
            <div className="ov-progress-row" key={row.key}>
              <div className="ov-progress-label"><Link to={row.href}>{row.title}</Link></div>
              <div className="ov-progress-track">
                <div className={`ov-progress-fill ${cls}`} style={{ width: `${total ? Math.min(100, fresh / total * 100) : 0}%` }} />
              </div>
              <div className="ov-progress-nums">
                {fresh}/{total}
                {dev != null && <span className="muted"> ({dev}/{devTotal})</span>}
              </div>
            </div>
          )
        })}
      </div>

      <div className="card">
        <h2>待办 <span className="muted">下一批要跑的正文页</span></h2>
        {!summary && !error && <p className="muted">加载中…</p>}
        {summary && (
          summary.next.todo > 0 ? (
            <>
              <p className="qs">正文页共 {summary.next.body_total} 页，已处理 {summary.next.done} 页，剩 {summary.next.todo} 页</p>
              {summary.next.batch.length > 0 && <div className="ov-todo-batch">{summary.next.batch.join(', ')}</div>}
              <p className="qs" style={{ marginTop: '.4rem' }}>
                <Link to={`/${book}/runs/`}>去运行页入队</Link>
              </p>
            </>
          ) : (
            <p className="ov-alert-row ov-ok">✓ 正文页 {summary.next.body_total} 页全部跑完</p>
          )
        )}
      </div>

      <div className="card">
        <h2>异常数据 <span className="muted">只读产物的轻量摘要，完整判据体检见「统计数据」页</span></h2>
        {!summary && !error && <p className="muted">加载中…</p>}
        {summary && (
          <>
            <div className={`ov-alert-row ${summary.rate.review ? 'ov-warn' : 'ov-ok'}`}>
              {summary.rate.rate != null ? (
                <>人审率 <b>{(summary.rate.rate * 100).toFixed(2)}%</b>
                  （{summary.rate.review}/{summary.rate.slots}）
                  {summary.rate.unseen_rate != null && <> · 未审段 {(summary.rate.unseen_rate * 100).toFixed(2)}%</>}
                </>
              ) : '还没有人审率数据'}
              <Link to={`/${book}/evals/`}>查体检</Link>
            </div>
            {summary.gates.map((g) => (
              <div key={g.gate} className={`ov-alert-row ${g.n_blocked ? 'ov-warn' : 'ov-ok'}`}>
                {g.n_blocked ? `✗ ${g.gate} 整页拦下 ${g.n_blocked} 页` : `✓ ${g.gate} 零整页拦截`}
                {Object.keys(g.tier_totals).length > 0 && (
                  <span className="muted">（列级：{Object.entries(g.tier_totals).map(([t, n]) => `${t} ${n}`).join('，')}）</span>
                )}
              </div>
            ))}
            <div className={`ov-alert-row ${summary.align_ref.n_not_anchored ? 'ov-warn' : 'ov-ok'}`}>
              整理本锚定 {summary.align_ref.n_anchored}/{summary.align_ref.n_pages - summary.align_ref.n_missing}
              {summary.align_ref.n_not_anchored > 0 && <>（未锚定 {summary.align_ref.n_not_anchored} 页）</>}
              <Link to={`/${book}/evals/`}>看明细</Link>
            </div>
            {llmStats?.has_data && (
              <div className="ov-alert-row muted">
                线上大模型裁决：{llmStats.n_total_calls} 次调用 · {llmStats.n_resolved} 条已核对人审 ·
                正确率 {llmStats.accuracy != null ? `${(llmStats.accuracy * 100).toFixed(1)}%` : '还没人审判定'}
              </div>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2>运行参数 <span className="muted">按本书写回 books/{book}.yaml</span></h2>
        {!status && !error && <p className="muted">加载中…</p>}
        {status && (
          <label className="qs" style={{ display: 'flex', alignItems: 'center', gap: '.5rem', cursor: ocrBusy ? 'wait' : 'pointer' }}>
            <input
              type="checkbox"
              checked={!!status.ocr_candidates_enabled}
              disabled={ocrBusy}
              onChange={(e) => toggleOcrCandidates(e.target.checked)}
            />
            <span>
              启用 Step5-c OCR候选
              <span className="muted">
                {' '}（默认关闭：整理本已足够准，主要依赖 5-a 库匹配 + 5-b 生僻字候选；勾选后本书批量跑会带上 5-c）
              </span>
            </span>
          </label>
        )}
        {ocrErr && <p className="error">{ocrErr}</p>}
      </div>
    </div>
  )
}
