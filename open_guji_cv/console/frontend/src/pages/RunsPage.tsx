import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { listPipelines } from '../api/registry'
import { submitRun, fetchRuns, cancelRun } from '../api/runs'
import { fmtDur } from '../api/client'
import { usePersistedPages } from '../hooks/usePersistedPages'
import type { Pipeline, StepDescribe } from '../types/registry'
import type { RunJob, LogEvent } from '../types/runs'
import './runs.css'

// D6：跨步页面 /<book>/runs/（v1 run tab）。服务任意 from→to 步骤区间，
// 不属于单一步，方案 §三：书级路由，不挂在 /<book>/step/.../ 下。
export function RunsPage() {
  const { book = '' } = useParams()
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [pipelineId, setPipelineId] = useState('keben_body_v2')
  const [fromStep, setFromStep] = useState('')
  const [toStep, setToStep] = useState('')
  const [pages, setPages] = usePersistedPages('runs', book, 'dev_set')
  const [paramsText, setParamsText] = useState('')
  const [llmEnable, setLlmEnable] = useState(false)
  const [llmProvider, setLlmProvider] = useState('qwen')
  const [force, setForce] = useState(false)
  const [allowSampleDb, setAllowSampleDb] = useState(false)
  const [runMsg, setRunMsg] = useState('')
  const [jobs, setJobs] = useState<RunJob[]>([])
  const [selJob, setSelJob] = useState<string | null>(null)
  const [logTitle, setLogTitle] = useState('')
  const [logLines, setLogLines] = useState<Array<{ text: string; cls: string }>>([])
  const esRef = useRef<EventSource | null>(null)
  const logRef = useRef<HTMLPreElement>(null)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const steps: StepDescribe[] = pipelines.find((p) => p.id === pipelineId)?.steps || []

  useEffect(() => {
    listPipelines().then((ps: Pipeline[]) => { setPipelines(ps); if (ps[0]) setPipelineId(ps[0].id) }).catch(() => {})
  }, [])

  useEffect(() => {
    if (steps.length && !toStep) setToStep(steps[steps.length - 1].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steps])

  async function pollJobs() {
    if (pollTimer.current) clearTimeout(pollTimer.current)
    let list: RunJob[] = []
    try {
      list = await fetchRuns(30)
      setJobs(list)
    } catch {
      // 轮询失败下一轮再试
    }
    const active = list.some((j) => ['pending', 'running'].includes(j.status))
    pollTimer.current = setTimeout(pollJobs, active ? 2000 : 8000)
  }

  useEffect(() => {
    pollJobs()
    return () => { if (pollTimer.current) clearTimeout(pollTimer.current); esRef.current?.close() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function selectJob(id: string) {
    esRef.current?.close()
    setSelJob(id)
    setLogTitle(id)
    setLogLines([])
    const es = new EventSource(`/api/runs/${id}/log`)
    esRef.current = es
    es.onmessage = (m) => {
      const d: LogEvent = JSON.parse(m.data)
      if (d.type === 'line') {
        let cls = ''
        if (/失败|阻塞|Error|Traceback/.test(d.line)) cls = 'fail'
        else if (/完成/.test(d.line)) cls = 'ok'
        else if (/跳过/.test(d.line)) cls = 'skip'
        setLogLines((prev) => [...prev, { text: d.line, cls }])
      } else if (d.type === 'complete') {
        setLogLines((prev) => [...prev, { text: `— ${d.status}，退出码 ${d.exit_code}，${fmtDur(d.duration)} —`, cls: d.status === 'completed' ? 'ok' : 'fail' }])
        es.close()
        esRef.current = null
        pollJobs()
      }
    }
    pollJobs()
  }

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logLines])

  async function onSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    let params: Record<string, unknown> = {}
    const raw = paramsText.trim()
    if (raw) {
      try {
        params = JSON.parse(raw)
      } catch (e) {
        setRunMsg('参数 JSON 不合法：' + (e as Error).message)
        return
      }
    }
    if (llmEnable) {
      params.context_decide = { ...(params.context_decide as object || {}), enable_online_llm: true, llm_provider: llmProvider }
    } else if (params.context_decide && typeof params.context_decide === 'object' && 'enable_online_llm' in params.context_decide) {
      (params.context_decide as Record<string, unknown>).enable_online_llm = false
    }
    try {
      const job = await submitRun({
        book, pipeline: pipelineId,
        from_step: fromStep || undefined, to_step: toStep || undefined,
        pages: pages || 'dev_set', force, params, allow_sample_db: allowSampleDb,
      })
      setRunMsg(`已入队 ${job.id}`)
      await pollJobs()
      selectJob(job.id)
    } catch (e) {
      setRunMsg('入队失败：' + (e as Error).message)
    }
  }

  async function onCancel(id: string) {
    await cancelRun(id)
    pollJobs()
  }

  return (
    <div>
      <div className="card">
        <h2>入队一次运行</h2>
        <form className="run" onSubmit={onSubmit}>
          <label>从步骤
            <select value={fromStep} onChange={(e) => setFromStep(e.target.value)}>
              <option value="">首</option>
              {steps.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.title}</option>)}
            </select>
          </label>
          <label>到步骤
            <select value={toStep} onChange={(e) => setToStep(e.target.value)}>
              {steps.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.title}</option>)}
            </select>
          </label>
          <label>页 <input value={pages} onChange={(e) => setPages(e.target.value)} /></label>
          <label><span>参数覆盖（JSON，可空）</span>
            <textarea value={paramsText} onChange={(e) => setParamsText(e.target.value)} placeholder='{"column_gate": {"width_tol": 0.2}}' />
          </label>
          <label className="run-row" style={{ gridColumn: '1 / -1' }}
                 title="Step6 上下文裁决：候选内字位过不了 margin_gate 门槛时，线上真问一次大模型调候选顺序——不自动放行，仍要人审。会产生 API 账单">
            <input type="checkbox" checked={llmEnable} onChange={(e) => setLlmEnable(e.target.checked)} /> 启用线上大模型裁决（会产生 API 费用）
            <select value={llmProvider} onChange={(e) => setLlmProvider(e.target.value)} style={{ marginLeft: '.4rem' }}>
              <option value="qwen">qwen（离线评测最优，推荐）</option>
              <option value="glm">glm</option>
            </select>
          </label>
          <label className="run-row" style={{ gridColumn: '1 / -1' }}>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 强制重跑（无视指纹）
          </label>
          <label className="run-row" style={{ gridColumn: '1 / -1' }}
                 title="没设 GUJI_WORKSPACE 时默认拒绝入队——真要跑书请设 GUJI_WORKSPACE，这个勾选只用于本地示例库试跑">
            <input type="checkbox" checked={allowSampleDb} onChange={(e) => setAllowSampleDb(e.target.checked)} /> 允许用本地示例库（没设 GUJI_WORKSPACE 时勾选才能入队）
          </label>
          <div style={{ gridColumn: '1 / -1' }}><button className="primary" type="submit">入队</button></div>
        </form>
        <div className="muted">{runMsg}</div>
      </div>
      <div className="card">
        <h2>任务 <span className="muted">串行执行，最新在上</span></h2>
        <table className="jobs">
          <thead><tr><th>任务</th><th>册 / 管线</th><th>范围</th><th>页</th><th>状态</th><th>时长</th><th></th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className={j.id === selJob ? 'sel' : ''} onClick={() => selectJob(j.id)}>
                <td className="mono">{j.id.slice(4)}</td>
                <td>{j.spec.book} / {j.spec.pipeline}</td>
                <td className="mono">{j.spec.from_step || '首'} → {j.spec.to_step || '末'}{j.spec.force ? ' !' : ''}</td>
                <td className="mono">{j.spec.pages}</td>
                <td><span className={`badge b-${j.status}`}>{j.status}</span></td>
                <td className="mono">{fmtDur(j.duration)}</td>
                <td>{['pending', 'running'].includes(j.status) && (
                  <button className="danger" onClick={(ev) => { ev.stopPropagation(); onCancel(j.id) }}>取消</button>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h2>日志 <span className="muted">{logTitle}</span></h2>
        <pre className="log" ref={logRef}>
          {logLines.map((l, i) => <span key={i} className={l.cls}>{l.text}{'\n'}</span>)}
        </pre>
      </div>
    </div>
  )
}
