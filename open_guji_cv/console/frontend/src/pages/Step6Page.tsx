import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchLlmOnlineCalls, fetchLlmOnlineStats } from '../api/llmOnline'
import type { LlmOnlineCall, LlmOnlineCallsResponse, LlmOnlineStats } from '../api/llmOnline'

// Step6 上下文裁决：展示线上大模型单次调用的输入/输出/决定
// （overview 2026-09-11 下发，见 项目进展/图片初步数字化/进度/
// Step6-上下文裁决/03-大模型产物展示.md）。
//
// 数据源是 `output/llm_online_calls/<book>.jsonl`（`context_decide.py`
// 只在 `gated_ngram` 过不了 margin_gate 时才问模型，见模块头
// 【2026-09-10】）——聚合数字已经有 `/api/llm_online_stats`（总览页那行
// 简报），这里补的是"点开一条看完整输入输出"，不重新统计。
export function Step6Page() {
  const { book = '' } = useParams()
  const [stats, setStats] = useState<LlmOnlineStats | null>(null)
  const [data, setData] = useState<LlmOnlineCallsResponse | null>(null)
  const [err, setErr] = useState('')
  const [pageFilter, setPageFilter] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    setStats(null)
    setData(null)
    setErr('')
    setOpenId(null)
    if (!book) return
    fetchLlmOnlineStats(book).then(setStats).catch(() => setStats(null))
    const p = pageFilter.trim() ? Number(pageFilter.trim()) : undefined
    fetchLlmOnlineCalls(book, p).then(setData).catch((e) => setErr((e as Error).message))
  }, [book, pageFilter])

  const rows = data?.rows ?? []
  const openRow = useMemo(() => rows.find((r) => r.id === openId) ?? null, [rows, openId])

  if (!stats?.has_data && !err) {
    return (
      <div className="card">
        <h2>Step6 上下文裁决 · 大模型调用记录</h2>
        <p className="muted">
          还没有线上调用日志——`enable_online_llm` 默认关闭，
          「运行」面板勾选「启用线上大模型裁决」并跑一遍之后，这里才有数据。
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <h2>Step6 上下文裁决 · 大模型调用记录</h2>
        {stats && (
          <div className="counts" style={{ marginBottom: '.6rem' }}>
            <span className="s-fresh">共 {stats.n_total_calls} 次调用</span>
            <span className="muted">候选内命中 {stats.n_answered_in_candidates ?? '—'}</span>
            <span className="muted">
              已核对人审 {stats.n_resolved ?? 0}
              {stats.accuracy != null && <>（正确率 {(stats.accuracy * 100).toFixed(1)}%）</>}
            </span>
          </div>
        )}
        {stats?.by_model && Object.keys(stats.by_model).length > 0 && (
          <p className="muted" style={{ fontSize: '.85rem' }}>
            按 model：
            {Object.entries(stats.by_model).map(([k, v]) => (
              <span key={k} style={{ marginRight: '1rem' }}>
                {k}：{v.n} 条，{(v.accuracy * 100).toFixed(1)}%
              </span>
            ))}
          </p>
        )}
        <label className="muted" style={{ fontSize: '.85rem' }}>
          按页筛选：
          <input
            type="number"
            value={pageFilter}
            onChange={(e) => setPageFilter(e.target.value)}
            placeholder="留空看全部"
            style={{ width: '6rem', marginLeft: '.4rem' }}
          />
        </label>
      </div>

      {err && <div className="card"><p className="muted">{err}</p></div>}

      {data && (
        <div className="card">
          <p className="muted">
            {data.total} 条{data.total > rows.length ? `（只显示最近 ${rows.length} 条）` : ''}
          </p>
          <table className="mono" style={{ width: '100%', fontSize: '.82rem', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left' }}>
                <th>字位</th>
                <th>候选</th>
                <th>模型答案</th>
                <th>命中候选内</th>
                <th>耗时</th>
                <th>tokens</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => setOpenId(r.id === openId ? null : r.id)}
                  style={{ cursor: 'pointer', background: r.id === openId ? 'var(--row-active, rgba(127,127,127,.12))' : undefined }}
                >
                  <td>{r.id}</td>
                  <td>{r.candidates_chars.join('')}</td>
                  <td>
                    {r.llm_parsed_char ?? <span className="muted">（解析失败）</span>}
                    {r.error && <span className="s-failed"> ⚠</span>}
                  </td>
                  <td>{r.llm_answer_in_candidates ? '✓' : '✗'}</td>
                  <td>{r.latency_s.toFixed(2)}s{r.cached && <span className="muted">（缓存）</span>}</td>
                  <td>{r.prompt_tokens ?? '—'}+{r.completion_tokens ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openRow && <CallDetail row={openRow} />}
    </div>
  )
}

// 单条调用详情：输入（上下文+候选）/ 输出（原始回答+解析结果）/ 决定
// （是否命中候选内，是否会被 context_decide 拿去重排 ranked）。
function CallDetail({ row }: { row: LlmOnlineCall }) {
  return (
    <div className="card">
      <h3>{row.id} <span className="muted">{row.provider}/{row.model} · {row.ts}</span></h3>

      <div style={{ marginBottom: '.6rem' }}>
        <div className="muted">输入</div>
        <div className="mono">
          {row.context_before}
          <span style={{ padding: '0 .2rem', border: '1px dashed currentColor' }}>△</span>
          {row.context_after}
        </div>
        <div className="muted" style={{ marginTop: '.3rem' }}>
          候选：{row.candidates_chars.join('、')}
        </div>
      </div>

      <div style={{ marginBottom: '.6rem' }}>
        <div className="muted">输出</div>
        <div className="mono" style={{ whiteSpace: 'pre-wrap' }}>{row.llm_raw_text || <span className="muted">（空）</span>}</div>
        <div className="muted" style={{ marginTop: '.3rem' }}>
          解析出的字：{row.llm_parsed_char ?? '（解析失败）'}
          {' '}· 解析{row.llm_parse_ok ? '成功' : '失败'}
          {' '}· {row.llm_answer_in_candidates ? '落在候选内' : '不在候选内（不会被采信）'}
        </div>
        {row.error && <div className="s-failed">错误：{row.error}</div>}
      </div>

      <div>
        <div className="muted">决定</div>
        <div className="muted">
          {row.llm_answer_in_candidates
            ? '这次调用会把该字重排到 ranked 最前面（context_decide.py 铁律：只调顺序，不碰 char/source）'
            : '答案不在候选内或解析失败，本次调用不产生任何影响，字位仍按原顺序落回人审'}
          {' '}· 耗时 {row.latency_s.toFixed(2)}s（{row.cached ? '命中缓存' : '真实请求'}）
          {' '}· token {row.prompt_tokens ?? '—'} + {row.completion_tokens ?? '—'}
        </div>
      </div>
    </div>
  )
}
