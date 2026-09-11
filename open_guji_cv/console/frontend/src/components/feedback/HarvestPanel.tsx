import { useEffect, useState } from 'react'
import { fetchBatches, harvestBatch, routeBatch, fetchGoldShards, migrateGold, driftGold } from '../../api/feedback'
import type { Batch, GoldShard } from '../../types/feedback'
import './feedback.css'

// 迁移自 v1 static/js/panels/harvest.js（80 行）。三件事一个面板：
// 审查批次台账、收割（外部审查页读回的内容变成事件）、按路由表消费。
// 在本控制台裁决的提交时就已经落库了，这里的按钮是"补跑"用的。
export function HarvestPanel() {
  const [batches, setBatches] = useState<Batch[]>([])
  const [bmsg, setBmsg] = useState('')
  const [gold, setGold] = useState<GoldShard[]>([])
  const [goldOut, setGoldOut] = useState('')
  const [hBatch, setHBatch] = useState('')
  const [hText, setHText] = useState('')
  const [hOut, setHOut] = useState('')

  async function loadBatches() {
    try {
      const bs = await fetchBatches()
      setBatches(bs)
      if (!hBatch && bs.length) setHBatch(bs[0].id)
    } catch (e) {
      setBmsg((e as Error).message)
    }
    loadGold()
  }

  async function loadGold() {
    try {
      setGold((await fetchGoldShards()).shards)
    } catch (e) {
      setGoldOut((e as Error).message)
    }
  }

  useEffect(() => { loadBatches() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function doHarvest() {
    if (!hBatch || !hText.trim()) { setHOut('选批次、贴内容'); return }
    const b = batches.find((x) => x.id === hBatch)
    try {
      const r = await harvestBatch(hBatch, b?.step || '', b?.kind || 'verdict', hText)
      setHOut(JSON.stringify(r, null, 1))
      loadBatches()
    } catch (e) {
      setHOut('收割失败：' + (e as Error).message)
    }
  }

  async function doRoute(dry: boolean) {
    if (!hBatch) return
    try {
      const r = await routeBatch(hBatch, dry)
      setHOut(JSON.stringify(r, null, 1))
      loadBatches()
    } catch (e) {
      setHOut('消费失败：' + (e as Error).message)
    }
  }

  async function doMigrate(shard: string) {
    try {
      setGoldOut(JSON.stringify(await migrateGold(shard), null, 1))
      loadGold()
    } catch (e) {
      setGoldOut((e as Error).message)
    }
  }

  async function doDrift(shard: string) {
    setGoldOut('检查中…')
    try {
      setGoldOut(JSON.stringify(await driftGold(shard), null, 1))
    } catch (e) {
      setGoldOut((e as Error).message)
    }
  }

  return (
    <>
      <div className="card">
        <h2>审查批次 <span className="muted">取代手写的 artifacts/README.md 台账</span></h2>
        <table className="jobs">
          <thead>
            <tr><th>批次</th><th>题目</th><th>步骤</th><th>传输</th><th>卡片</th><th>已裁</th><th>已消费</th><th>状态</th><th></th></tr>
          </thead>
          <tbody>
            {batches.length ? batches.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.id}</td>
                <td>{b.title}</td>
                <td className="mono">{b.step}</td>
                <td>{b.transport}{b.url && <> <a href={b.url} target="_blank" rel="noopener noreferrer">链接</a></>}</td>
                <td className="mono">{b.n_cards}</td>
                <td className="mono">{b.n_events}</td>
                <td className="mono">{b.n_consumed}</td>
                <td><span className={`badge b-${b.status === 'harvested' ? 'completed' : (b.status === 'open' ? 'running' : 'pending')}`}>{b.status}</span></td>
                <td><button onClick={() => { setHBatch(b.id); doRoute(false) }}>消费</button></td>
              </tr>
            )) : (
              <tr><td colSpan={9} className="muted">还没有批次。用 CLI 建：guji-cv batch new …</td></tr>
            )}
          </tbody>
        </table>
        <div className="muted">{bmsg}</div>
      </div>

      <div className="card">
        <h2>收割与消费 <span className="muted">裁决 → 事件 → 字形库 / 测试集</span></h2>
        <p className="muted feedback-help">
          在本控制台裁决的提交时就已经落库了，这里不用再点一次；
          下面这几个按钮是补跑用的：裁决来自外部审查页（先"收割"成事件）、
          自动消费报错了、或想先"试算"看看。三步的关系：
          <span className="mono">外部页 →(收割)→ 事件 →(消费)→ 字形库 / 测试集</span>
          <br />消费是幂等的，重复点不会重复写。
        </p>
        <div className="feedback-row">
          <label className="muted">批次
            <select value={hBatch} onChange={(e) => setHBatch(e.target.value)}>
              {batches.map((b) => <option key={b.id} value={b.id}>{b.id}</option>)}
            </select>
          </label>
          <button onClick={doHarvest} title="把外部审查页读回的内容变成事件">收割</button>
          <button onClick={() => doRoute(true)} title="消费的预览：一个字都不写">试算</button>
          <button className="primary" onClick={() => doRoute(false)} title="真正落库">按路由表消费</button>
        </div>
        <textarea className="feedback-textarea" value={hText} onChange={(e) => setHText(e.target.value)}
                  placeholder="粘贴审查页 HTML、verdicts JSONL、GUJI-SEED-EVENT 日志，或 marks JSON" />
        <pre className="json feedback-out">{hOut}</pre>
      </div>

      <div className="card">
        <h2>金标分片 <span className="muted">载体 items 的已迁；其余由适配器读旧格式</span></h2>
        <table className="jobs">
          <thead>
            <tr><th>分片</th><th>载体</th><th>条数</th><th>状态</th><th>分层</th><th></th></tr>
          </thead>
          <tbody>
            {gold.map((s) => {
              const st = Object.entries(s.status || {}).map(([k, v]) => `${k} ${v}`).join(' / ')
              const str = Object.entries(s.stratum || {}).map(([k, v]) => `${k} ${v}`).join(' / ') || '—'
              const migrated = s.carrier === 'items'
              return (
                <tr key={s.shard}>
                  <td className="mono">{s.shard}</td>
                  <td><span className={`badge b-${migrated ? 'completed' : 'pending'}`}>{s.carrier}</span></td>
                  <td className="mono">{s.n}</td>
                  <td className="mono">{st}</td>
                  <td className="mono">{str}</td>
                  <td>{migrated
                    ? <button onClick={() => doDrift(s.shard)}>漂移检查</button>
                    : <button onClick={() => doMigrate(s.shard)}>迁移</button>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <pre className="json feedback-out">{goldOut}</pre>
      </div>
    </>
  )
}
