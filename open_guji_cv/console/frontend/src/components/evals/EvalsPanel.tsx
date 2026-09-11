import { useEffect, useRef, useState } from 'react'
import { fetchEvals, runEval } from '../../api/evals'
import type { EvalRunResult, EvalSpec } from '../../types/evals'
import './evals.css'

// 迁移自 v1 static/js/panels/evals.js（44 行）。27 个评测脚本；报告带分母、
// 分层与过期金标数。跑单个/全部轻量的，输出最近一次结果的 JSON。
export function EvalsPanel() {
  const [list, setList] = useState<EvalSpec[]>([])
  const [msg, setMsg] = useState('')
  const [out, setOut] = useState('')
  const results = useRef<Record<string, EvalRunResult>>({})
  const [, bump] = useState(0)

  async function load() {
    try {
      setList(await fetchEvals())
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  useEffect(() => { load() }, [])

  async function runOne(id: string, quiet?: boolean) {
    if (!quiet) setMsg(`${id} 跑中…`)
    try {
      const r = await runEval(id)
      results.current[id] = r
      setOut(JSON.stringify(r, null, 1).slice(0, 4000))
      bump((n) => n + 1)
    } catch (e) {
      setOut(`${id}: ${(e as Error).message}`)
    }
    if (!quiet) setMsg('')
  }

  async function runAll() {
    const runnables = list.filter((s) => s.runnable)
    setMsg(`跑 ${runnables.length} 个…`)
    for (const s of runnables) await runOne(s.id, true)
    setMsg('完成')
  }

  return (
    <div className="card">
      <h2>评测器 <span className="muted">27 个 eval 脚本；报告带分母、分层与过期金标数</span></h2>
      <div className="evals-toolbar">
        <button onClick={runAll}>跑全部轻量的</button>
        <span className="muted">{msg}</span>
      </div>
      <table className="jobs">
        <thead>
          <tr><th>评测器</th><th>分片</th><th>状态</th><th>指标</th><th>金标</th><th></th></tr>
        </thead>
        <tbody>
          {list.map((s) => {
            const r = results.current[s.id]
            const badge = r
              ? <span className={`badge b-${r.status === 'ok' ? 'completed' : (r.status === 'regressed' ? 'running' : 'failed')}`}>{r.status}</span>
              : (s.runnable ? <span className="muted">未跑</span> : <span className="muted">{s.blocked}</span>)
            const ms = r ? (r.metrics || []).slice(0, 2).map((m) => `${m.name} ${m.value}${m.unit || ''}`).join('，') : ''
            const gold = r && r.n_gold != null ? `${r.n_gold}${r.stale_gold ? ` (过期 ${r.stale_gold})` : ''}` : ''
            return (
              <tr key={s.id}>
                <td className="mono">{s.id}</td>
                <td className="mono">{s.shard}</td>
                <td>{badge}</td>
                <td className="mono">{ms}</td>
                <td className="mono">{gold}</td>
                <td>{s.runnable && <button onClick={() => runOne(s.id)}>跑</button>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <pre className="json evals-out">{out}</pre>
    </div>
  )
}
