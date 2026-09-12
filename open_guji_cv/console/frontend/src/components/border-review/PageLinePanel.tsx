import { useEffect, useRef, useState } from 'react'
import { fetchPageLineCards, fetchPageLineVerdicts } from '../../api/borderPageLine'
import { postEvents } from '../../api/events'
import type { PageLineCard as Card } from '../../types/borderPageLine'
import { PageLineCard } from './PageLineCard'
import type { OffsetState } from './PageLineCard'
import './borderReview.css'

// linebot（逐列坐标金标）头一批 329 条抽查发现：窄列裁剪图里版框墨条常与
// 相邻字缝糊在一起分不清，标注系统性偏向"字开始的地方"，而且整页同向
// （不是列级噪声，是页级系统偏差）——用整页通栏带一眼就能看出哪条是贯穿
// 全页的印刷直线，比窄裁剪图清楚，效率也高：一页拖一条线（保留现役斜率，
// 只调整整体偏移），不必逐列点 9 次。

const STEP = 'border_detect'

export function PageLinePanel({ book }: { book: string }) {
  const [pages, setPages] = useState('dev_set')
  const [batchInput, setBatchInput] = useState('')
  const [onlyTodo, setOnlyTodo] = useState(true)
  const [cards, setCards] = useState<Card[]>([])
  const [msg, setMsg] = useState('')
  const [cur, setCur] = useState(0)
  const states = useRef<Record<string, OffsetState>>({})
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const batch = () => batchInput.trim() || `${book}-pageline-review`

  async function load() {
    setMsg('载入中…')
    const b = batch()
    let d
    try {
      d = await fetchPageLineCards(book, pages || 'dev_set')
    } catch (e) {
      setMsg('失败：' + (e as Error).message)
      return
    }
    let done: Record<string, { verdict: string; offset?: number | null }> = {}
    try {
      done = (await fetchPageLineVerdicts(b)).verdicts || {}
    } catch {
      // 新批次，没有裁决可读
    }
    const st: Record<string, OffsetState> = {}
    for (const c of d.cards) {
      const v = done[c.id]
      st[c.id] = { offset: v && v.offset != null ? v.offset : 0, done: v?.verdict }
    }
    states.current = st
    setCards(d.cards)
    setCur(0)
    setMsg(`${d.n} 张卡 → 批次 ${b}`)
    bump()
  }

  function setOffset(c: Card, offset: number) {
    states.current[c.id] = { ...states.current[c.id], offset }
    bump()
  }

  async function decide(c: Card, verdict: string) {
    const offset = verdict === 'ok' ? 0 : states.current[c.id]?.offset ?? 0
    const prev = states.current[c.id]
    states.current[c.id] = { offset, done: verdict }
    bump()
    try {
      await postEvents({
        batch: batch(), step: STEP, unit: 'page', kind: 'border_offset',
        events: [{ id: c.id, offset, verdict, t: Date.now() }],
      })
      const n = Object.values(states.current).filter((s) => s.done).length
      setMsg(`已裁 ${n} / ${cards.length} → 批次 ${batch()}`)
      if (!onlyTodo) focus(cur + 1)
    } catch (e) {
      states.current[c.id] = prev
      bump()
      setMsg('写入失败：' + (e as Error).message)
    }
  }

  const visible = onlyTodo ? cards.filter((c) => !states.current[c.id]?.done) : cards
  const curClamped = Math.max(0, Math.min(cur, visible.length - 1))

  function focus(i: number) {
    if (!visible.length) return
    const j = Math.max(0, Math.min(i, visible.length - 1))
    setCur(j)
    document.getElementById(`plc${j}`)?.scrollIntoView({ block: 'center' })
  }

  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      const c = visible[curClamped]
      if (!c) return
      const step = ev.shiftKey ? 10 : 2
      const st = states.current[c.id] || { offset: 0 }
      if (ev.key === 'ArrowUp') { setOffset(c, st.offset - step); ev.preventDefault() }
      else if (ev.key === 'ArrowDown') { setOffset(c, st.offset + step); ev.preventDefault() }
      else if (ev.key === 'Enter') { decide(c, 'moved'); ev.preventDefault() }
      else if (ev.key === 'o' || ev.key === 'O') { decide(c, 'ok'); ev.preventDefault() }
      else if (ev.key === 'n' || ev.key === 'N') { decide(c, 'no_line'); ev.preventDefault() }
      else if (ev.key === 'ArrowRight' || ev.key === 'j') { focus(curClamped + 1); ev.preventDefault() }
      else if (ev.key === 'ArrowLeft' || ev.key === 'k') { focus(curClamped - 1); ev.preventDefault() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, curClamped])

  return (
    <div className="card">
      <h2>整页下版框偏移金标 <span className="muted">通栏带看一整页，一页拖一条线，不逐列点</span></h2>
      <p className="muted br-howto">
        每张卡是整页宽度的一条通栏带，居中围着现役下版框线截出来。淡色斜线是
        现役位置（沿用现有斜率），拖动整条线上下平移贴到真正贯穿全页的那条
        印刷直线上——注意跟字缝、污渍、相邻条目分隔线区分，版框线一定是
        <b>贯穿整个页面宽度</b>的一条直线。贴合了点"落定此偏移"；本来就对点
        "现役线位置就对"；这页印得太淡看不出线点"看不出线"。
      </p>
      <div className="br-toolbar">
        <label className="muted">页 <input value={pages} onChange={(e) => setPages(e.target.value)} size={10} /></label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册自动命名" /></label>
        <label className="muted"><input type="checkbox" checked={onlyTodo} onChange={(e) => setOnlyTodo(e.target.checked)} /> 只看未裁</label>
        <button onClick={load}>载入</button>
        <span className="muted">{msg}</span>
      </div>
      {visible.length > 0 && (
        <p className="muted br-help">
          高亮框住的是当前卡；键盘：<b>↑/↓</b> 移线 2px（Shift 10px）· <b>回车</b> 落定此偏移 ·
          <b> O</b> 现役线位置就对 · <b>N</b> 看不出线 · <b>←/→</b>（或 <b>k/j</b>）切换卡片
        </p>
      )}
      <div className="brgrid">
        {visible.map((c, i) => (
          <PageLineCard key={c.id} idx={i} c={c} st={states.current[c.id] || { offset: 0 }}
                        isCurrent={i === curClamped} onFocus={() => setCur(i)}
                        onSetOffset={(o) => setOffset(c, o)} onDecide={(v) => decide(c, v)} />
        ))}
      </div>
    </div>
  )
}
