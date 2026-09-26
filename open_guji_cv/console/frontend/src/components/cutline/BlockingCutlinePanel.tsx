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
  // 用户 2026-09-11：「有时几个备选都不对，要让我自己画」——`drawing` 开启
  // 手画模式，`poly` 是正在画的折线点。落定时若 `poly.length >= 2`，优先
  // 用它而不是 `pick` 指的候选（两者互斥：一旦开始画，pick 的候选只作
  // 背景参考，不再是落定对象）。
  drawing: boolean
  poly: Array<[number, number]>
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

  // 用户 2026-09-11：一次载入 250 条太多，多数一屏都刷不完；限到 30。
  const LOAD_LIMIT = 30

  async function load() {
    const b = batch()
    setMsg('载入中…（首次要做整理本对齐，约一分钟）')
    let d
    try {
      d = await fetchCutlineCases(book, pages, LOAD_LIMIT, b, true, 'all', 'blocking')
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
      const st: CardState = { pick: c.chosen ?? null, done: undefined, drawing: false, poly: [] }
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
    if (d.n === 0) {
      setMsg('没有待裁的切分方案——字卡不会被挡')
    } else {
      const more = d.n_r2s > d.n ? `，全部待裁 ${d.n_r2s} 条，裁完这批再刷新拿下一批` : ''
      // 整理本期望是裁切法的主要依据，锚不上就等于蒙着裁——宁可吵一点也要说破。
      // d.warn 是语料本身读错了（环境变量漏带）；n_expect 是语料对但这批页锚不上。
      const bad = d.warn
        ? `　⚠️ ${d.warn}`
        : (d.n_expect === 0 ? '　⚠️ 本批一条都没锚上整理本，「整理本期望」不可信' : '')
      setMsg(`本次载入 ${d.n} 条${more} → 批次 ${b}${bad}`)
    }
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
    const st = cardState.current[c.id]
    st.pick = k
    st.drawing = false   // 选了算法候选就退出手画模式，两者互斥
    bump()
  }

  function toggleDrawing(i: number) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    st.drawing = !st.drawing
    bump()
  }

  function addPoint(i: number, x: number, y: number) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    const yy = Math.max(c.crop_y0 + 1, Math.min(c.crop_y1 - 1, Math.round(y)))
    st.poly.push([Math.round(x), yy])
    bump()
  }

  function movePoint(i: number, k: number, x: number, y: number) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    if (!st.poly[k]) return
    st.poly[k] = [Math.round(x), Math.max(c.crop_y0 + 1, Math.min(c.crop_y1 - 1, Math.round(y)))]
    bump()
  }

  function removePoint(i: number, k: number) {
    const c = cases[i]
    if (!c) return
    cardState.current[c.id].poly.splice(k, 1)
    bump()
  }

  function clearPoly(i: number) {
    const c = cases[i]
    if (!c) return
    cardState.current[c.id].poly = []
    bump()
  }

  async function decide(i: number, verdict: 'confirmed' | 'idk') {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    const k = st.pick
    const drawn = st.poly.length >= 2
    if (verdict === 'confirmed' && k == null && !drawn) {
      setMsg('先选一个候选切法，或自己画一条线再落定'); return
    }
    const cd = !drawn && k != null ? c.candidates[k] : undefined

    const now = Date.now()
    let y = c.y
    let polyline: Array<[number, number]> | undefined
    let cand: string | undefined
    if (verdict === 'confirmed' && drawn) {
      const pts = st.poly.slice().sort((a, b) => a[0] - b[0])
      polyline = pts
      y = Math.round(pts.reduce((a, q) => a + q[1], 0) / pts.length)
    } else if (verdict === 'confirmed' && cd) {
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
      id: c.id, y, y_old: c.y,
      verdict: verdict === 'idk' ? 'idk' : (drawn ? 'moved' : (k === c.chosen ? 'ok' : 'moved')),
      bi: c.bi, slot_above: c.slot_above, slot_below: c.slot_below, col_h: c.col_h,
      // char_* = 整理本在这一位印的字（v2_align 的 ref）；shape_* = v2 定字认的刻本形。
      // 2026-09-13 之前 char_* 存的其实是 shape，两层混记；此后分开存，
      // 历史事件里的 char_* 要按 shape 理解（见 eval/touching.attach_expected）。
      char_above: c.char_above || '', char_below: c.char_below || '',
      shape_above: c.shape_above || '', shape_below: c.shape_below || '',
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

  // 键盘快捷键（用户 2026-09-16：「切分裁决卡片不支持键盘控制」）。按键
  // 语义尽量与 Step3 `CutlinePanel` 对齐（Enter 落定 / S 拿不准 / J·K 或
  // ←→ 换卡 / P 自己画 / X 清空 / Backspace 删最后一点 / U 重做），另加
  // 1–9 选候选——这个板块的核心动作就是「选第几种切法」。
  //
  // ⚠️ `cur` 是 `cases` 的下标，而落定过的卡片不渲染；直接 cur±1 会走进
  // 已隐藏的卡里（看着像按键没反应）。所以导航一律在 `visibleCases()` 的
  // 序里走，与 `focus()` 的口径一致。
  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      const vis = visibleCases()
      if (!vis.length) return
      // cur 指的卡若已落定（刚裁完那张），退到可见序的开头。
      const c = cases[cur]
      const vi = c && !cardState.current[c.id]?.done ? vis.indexOf(c) : 0
      const i = cases.indexOf(vis[vi])
      const st = cardState.current[vis[vi].id]
      if (ev.key === 'Enter') { decide(i, 'confirmed'); ev.preventDefault() }
      else if (ev.key === 's' || ev.key === 'S') { decide(i, 'idk'); ev.preventDefault() }
      else if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown' || ev.key === 'j') { focus(vi + 1); ev.preventDefault() }
      else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp' || ev.key === 'k') { focus(vi - 1); ev.preventDefault() }
      else if (/^[1-9]$/.test(ev.key)) {
        const k = +ev.key - 1
        if (k < (vis[vi].candidates || []).length) { pick(i, k); ev.preventDefault() }
      } else if (ev.key === 'p' || ev.key === 'P') { toggleDrawing(i); ev.preventDefault() }
      else if (ev.key === 'Backspace') {
        if (st.poly.length) removePoint(i, st.poly.length - 1)
        ev.preventDefault()
      } else if (ev.key === 'x' || ev.key === 'X') { clearPoly(i); ev.preventDefault() }
      else if (ev.key === 'u' || ev.key === 'U') { reopen(i); ev.preventDefault() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cases, cur])

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
          每行是一种切法：<b>字</b>是选它之后 Step5 库匹配认出的上/下格字，<b>百分比</b>是匹配置信度
          （没有单一答案时列出库给的候选池），<span className="clm-hit">绿色</span>＝与整理本期望字一致。
          点一行选中，「落定」确认，「拿不准」跳过留给下一轮。都不对时点「自己画」：
          点图空白处加点、拖动已有点、右键删点，画完直接「落定」。
          <br />
          键盘：<b>1–9</b> 选第几行切法 · <b>Enter</b> 落定 · <b>S</b> 拿不准 ·
          <b> J/K</b> 或 <b>←→↑↓</b> 换卡 · <b>P</b> 自己画 · <b>Backspace</b> 删最后一点 ·
          <b> X</b> 清空 · <b>U</b> 重做
        </p>
      )}
      <div className="bccgrid">
        {cases.map((c, i) => {
          const st = cardState.current[c.id]
          if (!st || st.done) return null
          return (
            <BlockingCutlineCard
              key={c.id} idx={i} c={c} pick={st.pick} done={st.done} isCurrent={i === cur}
              drawing={st.drawing} poly={st.poly}
              onFocus={() => setCur(i)}
              onPick={(k) => pick(i, k)}
              onConfirm={() => decide(i, 'confirmed')}
              onIdk={() => decide(i, 'idk')}
              onReopen={() => reopen(i)}
              onToggleDrawing={() => toggleDrawing(i)}
              onAddPoint={(x, y) => addPoint(i, x, y)}
              onMovePoint={(k, x, y) => movePoint(i, k, x, y)}
              onRemovePoint={(k) => removePoint(i, k)}
              onClearPoly={() => clearPoly(i)}
            />
          )
        })}
      </div>
    </div>
  )
}
