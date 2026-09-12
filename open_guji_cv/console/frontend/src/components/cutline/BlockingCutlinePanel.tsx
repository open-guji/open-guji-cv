import { useEffect, useRef, useState } from 'react'
import { fetchCutlineCases, fetchCutlineVerdicts } from '../../api/cutline'
import { postEvents } from '../../api/events'
import type { CutlineCase } from '../../types/cutline'
import { BlockingCutlineCard } from './BlockingCutlineCard'
import './cutline.css'

// Step7「切分裁决」板块（overview 2026-09-11 下发）。只出顺序闸正在挡住字卡
// 的那批多候选切点（`scope=blocking`，见 `console/routers/cutline.py`），
// 裁完调用 `onDecided` 通知外层刷新定字裁决。
//
// 故意不与 Step3 的 `CutlinePanel`/`CutlineCard` 共用状态机：那边要支撑拖
// 直线、画折线、干扰标签这些「攒 touching-cuts 金标」用的精细标注，这里
// 只需要「选一个候选、落定」，状态形状简单得多，硬塞进同一个组件反而
// 让两边的分支互相绕。

interface CardState {
  pick: number | null
  done?: string
}

export function BlockingCutlinePanel({ book, pages, onDecided }: {
  book: string; pages: string; onDecided?: () => void
}) {
  const [cases, setCases] = useState<CutlineCase[]>([])
  const [msg, setMsg] = useState('')
  const [cur, setCur] = useState(0)
  const cardState = useRef<Record<string, CardState>>({})
  const seenAt = useRef<Record<string, number>>({})
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const batch = () => `${book}-cutline-blocking`

  async function load() {
    const b = batch()
    setMsg('载入中…（首次要做整理本对齐，约一分钟）')
    let d
    try {
      d = await fetchCutlineCases(book, pages, 250, b, true, 'all', 'blocking')
    } catch (e) {
      setMsg('失败：' + (e as Error).message)
      return
    }
    let done: Record<string, { verdict: string; cand?: string }> = {}
    try {
      done = (await fetchCutlineVerdicts(b)).verdicts || {}
    } catch {
      // 新批次，没有裁决可读，忽略
    }
    const next: Record<string, CardState> = {}
    const t0 = Date.now()
    for (const c of d.cases) {
      seenAt.current[c.id] = t0
      const st: CardState = { pick: c.chosen ?? null, done: undefined }
      const dv = done[c.id]
      if (dv) {
        st.done = dv.verdict
        if (dv.cand) {
          const k = (c.candidates || []).findIndex((x) => x.kind === dv.cand)
          if (k >= 0) st.pick = k
        }
      }
      next[c.id] = st
    }
    cardState.current = next
    setCases(d.cases)
    setCur(0)
    setMsg(d.n === 0 ? '没有待裁的切分方案——字卡不会被挡' : `${d.n} 条切点待裁 → 批次 ${b}`)
  }

  // 挂载时自动载入一次；Step7 顶部统一页数选择区切页时跟着重载。
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book, pages])

  function visibleCases() {
    return cases.filter((c) => !cardState.current[c.id]?.done)
  }

  function focus(i: number) {
    const vis = visibleCases()
    if (!vis.length) return
    const j = Math.max(0, Math.min(i, vis.length - 1))
    setCur(cases.indexOf(vis[j]))
    document.getElementById(`bcc${cases.indexOf(vis[j])}`)?.scrollIntoView({ block: 'nearest' })
  }

  function pick(i: number, k: number) {
    const c = cases[i]
    if (!c) return
    cardState.current[c.id].pick = k
    bump()
  }

  async function decide(i: number, verdict: 'confirmed' | 'idk') {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    const k = st.pick
    if (verdict === 'confirmed' && k == null) { setMsg('先选一个候选切法再落定'); return }
    const cd = k != null ? c.candidates[k] : undefined

    const now = Date.now()
    let y = c.y
    let polyline: Array<[number, number]> | undefined
    let cand: string | undefined
    if (verdict === 'confirmed' && cd) {
      cand = cd.kind
      if (cd.y && cd.y.length) {
        const step = 6
        polyline = []
        for (let j = 0; j < cd.y.length; j += step) polyline.push([c.x0 + j, cd.y[j]])
        if ((cd.y.length - 1) % step) polyline.push([c.x0 + cd.y.length - 1, cd.y[cd.y.length - 1]])
        y = Math.round(cd.y.reduce((a, q) => a + q, 0) / cd.y.length)
      }
    }
    const row = {
      id: c.id, y, y_old: c.y, verdict: verdict === 'confirmed' ? (k === c.chosen ? 'ok' : 'moved') : 'idk',
      bi: c.bi, slot_above: c.slot_above, slot_below: c.slot_below, col_h: c.col_h,
      char_above: c.char_above || '', char_below: c.char_below || '',
      polyline, cand, client_ts: now,
      dwell_ms: seenAt.current[c.id] ? now - seenAt.current[c.id] : undefined,
    }
    const prevDone = st.done
    st.done = verdict
    bump()
    try {
      await postEvents({ batch: batch(), step: 'row_segment', unit: 'boundary', kind: 'cutline', events: [row] })
      const n = Object.values(cardState.current).filter((s) => s.done).length
      setMsg(`已落 ${n} / ${cases.length} 条 → 批次 ${batch()}`)
      onDecided?.()   // 通知外层（Step7）字卡可能已解锁，去重载一下
    } catch (e) {
      setMsg('写入失败：' + (e as Error).message)
      st.done = prevDone
      bump()
      return
    }
    focus(0)   // 落定的卡从「待裁」里消失，下一张自然顶上来
  }

  function reopen(i: number) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    st.done = undefined
    bump()
    focus(i)
    setMsg(`${c.id} 已重开，改完再落定（后到覆盖）`)
  }

  return (
    <div className="card">
      <h2>切分裁决 <span className="muted">顺序闸挡住的多候选切点：裁完这批，被挡的字卡才会出来</span></h2>
      <div className="cl-toolbar">
        <button onClick={load}>刷新</button>
        <span className="muted">{msg}</span>
      </div>
      {cases.length > 0 && (
        <p className="muted cl-help">
          每行是一种切法：<b>字</b>是选它之后 Step5 库匹配认出的上/下格字，<b>百分比</b>是匹配置信度，
          <span className="clm-hit">绿色</span>＝与整理本期望字一致。点一行选中，「落定」确认，
          「拿不准」跳过留给下一轮。图上高亮的虚线＝当前选中的切法。
        </p>
      )}
      <div className="clgrid">
        {cases.map((c, i) => {
          const st = cardState.current[c.id]
          if (!st || st.done) return null
          return (
            <BlockingCutlineCard
              key={c.id} idx={i} c={c} pick={st.pick} done={st.done} isCurrent={i === cur}
              onFocus={() => setCur(i)}
              onPick={(k) => pick(i, k)}
              onConfirm={() => decide(i, 'confirmed')}
              onIdk={() => decide(i, 'idk')}
              onReopen={() => reopen(i)}
            />
          )
        })}
      </div>
    </div>
  )
}
