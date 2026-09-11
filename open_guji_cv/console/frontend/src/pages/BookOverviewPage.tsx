import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchStatus } from '../api/status'
import { listPipelines } from '../api/registry'
import { fetchLlmOnlineStats } from '../api/llmOnline'
import type { StatusResponse } from '../types/status'
import type { Pipeline } from '../types/registry'
import type { LlmOnlineStats } from '../api/llmOnline'
import { StatusMatrix } from '../components/StatusMatrix'

// D2：这本书的总览——数据、进度，对应方案 §二 `/<book>/`（v1 的 overview tab）。
// 「可启动任务」（v1 的 run tab）按方案 §三 归到跨步页面 `/<book>/runs/`，
// 总览页留一个入口链接过去，不在这里重复放表单。
//
// DAG 图与线上大模型正确率提示条是 D2 当时的遗漏，D6 做评测页时才发现
// v1 总览页原本就有这两块，这里补齐（见 README D6 记账）。
export function BookOverviewPage() {
  const { book = '' } = useParams()
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [llmStats, setLlmStats] = useState<LlmOnlineStats | null>(null)

  useEffect(() => {
    setStatus(null)
    setError(null)
    fetchStatus(book, 'keben_body_v2').then(setStatus).catch((e) => setError(String(e)))
    listPipelines().then((ps) => setPipeline(ps.find((p) => p.id === 'keben_body_v2') || ps[0] || null)).catch(() => {})
    fetchLlmOnlineStats(book).then(setLlmStats).catch(() => setLlmStats(null))
  }, [book])

  return (
    <div>
      <div className="card">
        <h2>{book} 总览 {pipeline && <span className="mono ws-note">{pipeline.notes}</span>}</h2>
        {pipeline && (
          <div className="dag">
            {pipeline.steps.map((s, i) => (
              <span key={s.id}>
                <span className="node" title={`${s.consumes.join(',')} → ${s.produces.join(',')}`}>{s.id}</span>
                {i < pipeline.steps.length - 1 && <span className="arrow"> → </span>}
              </span>
            ))}
          </div>
        )}
        {status?.workspace?.is_sample_db && (
          <p className="error">⚠ 用的是仓内示例库（未设 GUJI_WORKSPACE）</p>
        )}
        {status?.running && <p className="muted">运行中：{status.running.id}</p>}
      </div>
      <div className="card">
        <h2>状态矩阵 <span className="muted">行 = 步骤，列 = 页；点步骤名跳到对应 Step 页面</span></h2>
        {error && <p className="error">{error}</p>}
        {!status && !error && <p className="muted">加载中…</p>}
        {status && <StatusMatrix book={book} status={status} />}
        {llmStats?.has_data && (
          <div className="muted mono llm-online-note">
            线上大模型裁决：{llmStats.n_total_calls} 次调用 ·
            {llmStats.n_resolved} 条已核对人审 ·
            正确率 {llmStats.accuracy != null ? `${(llmStats.accuracy * 100).toFixed(1)}%` : '还没人审判定'}
          </div>
        )}
      </div>
    </div>
  )
}
