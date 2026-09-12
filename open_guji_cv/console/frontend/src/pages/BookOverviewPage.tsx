import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchStatus, setOcrCandidates } from '../api/status'
import { fetchOverviewSummary } from '../api/evals'
import { fetchLlmOnlineStats } from '../api/llmOnline'
import type { StatusResponse } from '../types/status'
import type { OverviewSummaryResponse } from '../types/evals'
import type { LlmOnlineStats } from '../api/llmOnline'
import { STEPS } from '../steps'
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
  const [summary, setSummary] = useState<OverviewSummaryResponse | null>(null)
  const [llmStats, setLlmStats] = useState<LlmOnlineStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocrBusy, setOcrBusy] = useState(false)
  const [ocrErr, setOcrErr] = useState<string | null>(null)

  useEffect(() => {
    setStatus(null)
    setSummary(null)
    setLlmStats(null)
    setError(null)
    setOcrErr(null)
    fetchStatus(book, 'keben_body_v2').then(setStatus).catch((e) => setError(String(e)))
    fetchOverviewSummary(book).then(setSummary).catch((e) => setError(String(e)))
    fetchLlmOnlineStats(book).then(setLlmStats).catch(() => setLlmStats(null))
  }, [book])

  const total = status?.pages.length || 0

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
        <h2>{book} 总进度 <span className="muted">每步 fresh 产物 / 全书页数</span></h2>
        {!status && !error && <p className="muted">加载中…</p>}
        {status && STEPS.filter((s) => s.backendIds.length > 0).map((s) => {
          const sid = s.backendIds[0]
          const d = status.steps[sid]
          if (!d) return null
          const fresh = d.counts.fresh
          const cls = fresh === 0 ? 'empty' : (fresh >= total ? 'full' : 'partial')
          return (
            <div className="ov-progress-row" key={s.id}>
              <div className="ov-progress-label"><Link to={`/${book}/step/${s.id}/`}>{s.title}</Link></div>
              <div className="ov-progress-track">
                <div className={`ov-progress-fill ${cls}`} style={{ width: `${total ? Math.min(100, fresh / total * 100) : 0}%` }} />
              </div>
              <div className="ov-progress-nums">{fresh}/{total}</div>
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
