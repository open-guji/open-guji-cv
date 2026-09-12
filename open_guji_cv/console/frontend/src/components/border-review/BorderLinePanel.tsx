import { useEffect, useRef, useState } from 'react'
import { fetchBorderLineCards, fetchBorderLineVerdicts } from '../../api/borderLine'
import { postEvents } from '../../api/events'
import { usePersistedPages } from '../../hooks/usePersistedPages'
import type { BorderLineCard as Card } from '../../types/borderLine'
import { BorderLineCard } from './BorderLineCard'
import type { LineState } from './BorderLineCard'
import './borderReview.css'

// `01-下版框根修先造金标.md`：下版框根修一直没做，卡在「没有口径统一的直接
// 坐标金标」——既有 14 页 border-detection 金标外延/内沿/中心口径混杂，
// column-warp 那批只点类别不标坐标。这张面板专造这批坐标金标：卡上给列图
// 下端裁剪图 + 投影，人拖一条线标"版框线在哪"，口径固定为与
// `border_bottom_in_column` 同一原点的裁剪图坐标（导出时再转页面坐标）。

const STEP = 'border_detect'

export function BorderLinePanel({ book }: { book: string }) {
  const [pages, setPages] = usePersistedPages('linebot', book, 'dev_set')
  const [batchInput, setBatchInput] = useState('')
  const [onlyTodo, setOnlyTodo] = useState(true)
  const [cards, setCards] = useState<Card[]>([])
  const [msg, setMsg] = useState('')
  const [cur, setCur] = useState(0)
  const states = useRef<Record<string, LineState>>({})
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const batch = () => batchInput.trim() || `${book}-linebot-review`

  async function load() {
    setMsg('载入中…')
    const b = batch()
    let d
    try {
      d = await fetchBorderLineCards(book, pages || 'dev_set')
    } catch (e) {
      setMsg('失败：' + (e as Error).message)
      return
    }
    let done: Record<string, { verdict: string; y?: number | null }> = {}
    try {
      done = (await fetchBorderLineVerdicts(b)).verdicts || {}
    } catch {
      // 新批次，没有裁决可读
    }
    const st: Record<string, LineState> = {}
    for (const c of d.cards) {
      const v = done[c.id]
      st[c.id] = { y: v && v.y != null ? v.y : c.y0, done: v?.verdict }
    }
    states.current = st
    setCards(d.cards)
    setCur(0)
    setMsg(`${d.n} 张卡 → 批次 ${b}`)
    bump()
  }

  function setY(c: Card, y: number) {
    states.current[c.id] = { ...states.current[c.id], y }
    bump()
  }

  async function decide(c: Card, verdict: string) {
    const y = verdict === 'ok' ? c.y0 : states.current[c.id]?.y ?? c.y0
    const prev = states.current[c.id]
    states.current[c.id] = { y, done: verdict }
    bump()
    try {
      await postEvents({
        batch: batch(), step: STEP, unit: 'column', kind: 'border_line',
        events: [{ id: c.id, y, y_old: c.y0, verdict, col_h: c.col_h, t: Date.now() }],
      })
      const n = Object.values(states.current).filter((s) => s.done).length
      setMsg(`已裁 ${n} / ${cards.length} → 批次 ${batch()}`)
      // 只看未裁时，落定的卡会从 visible 里消失——同一个下标自然滑到下一张，
      // 不用手动挪 cur；全量模式卡还留在原处，得显式前进一张（照抄 CutlinePanel）。
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
    document.getElementById(`blc${j}`)?.scrollIntoView({ block: 'nearest' })
  }

  // 键盘快捷键：只在本面板挂载时生效，照抄 CutlinePanel 的方案
  // （拖线用箭头、落定用回车/字母、翻卡用左右箭头）。
  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      const c = visible[curClamped]
      if (!c) return
      const step = ev.shiftKey ? 5 : 1
      const st = states.current[c.id] || { y: c.y0 }
      if (ev.key === 'ArrowUp') { setY(c, st.y - step); ev.preventDefault() }
      else if (ev.key === 'ArrowDown') { setY(c, st.y + step); ev.preventDefault() }
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
      <h2>下版框坐标金标 <span className="muted">拖线标版框线在哪，不是判切得对不对</span></h2>
      <p className="muted br-howto">
        每张卡是一列的下端裁剪图 + 右侧水平投影。淡色横线不是"算法探测的版框
        位置"——现在的窗口下界就是拿 BOTTOM_PAD 常量往下量出来的，这条线在每张
        卡上都落在同一行，只是给你一把固定的尺子。拖一条新线到你看到版框线
        真正所在的地方再点"落定此线"；淡色线本来就压准了就点"淡色线位置就对"；
        这页版框太淡/被裁没印出来看不出线，点"看不出线"，不要硬标一个坐标。
        口径固定为外沿——线压在版框墨条的最外沿（离字更远的那一侧）。
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
          高亮框住的是当前卡；键盘：<b>↑/↓</b> 拖线 1px（Shift 5px）· <b>回车</b> 落定此线 ·
          <b> O</b> 淡色线位置就对 · <b>N</b> 看不出线 · <b>←/→</b>（或 <b>k/j</b>）切换卡片
        </p>
      )}
      <div className="brgrid">
        {visible.map((c, i) => (
          <BorderLineCard key={c.id} idx={i} c={c} st={states.current[c.id] || { y: c.y0 }}
                          isCurrent={i === curClamped} onFocus={() => setCur(i)}
                          onSetY={(y) => setY(c, y)} onDecide={(v) => decide(c, v)} />
        ))}
      </div>
    </div>
  )
}
