import { useEffect, useRef, useState } from 'react'
import { fetchCutlineCases, fetchCutlineVerdicts } from '../../api/cutline'
import { postEvents } from '../../api/events'
import type { CutlineCase } from '../../types/cutline'
import { CutlineCard, type CardState } from './CutlineCard'
import './cutline.css'

// 迁移自 v1 static/js/panels/cutline.js（398 行，方案 §四标注「改造复用（分文件）」）。
// 用户 2026-09-05：「先让我添加一些金标，确定理想位置，再想算法。」
// 核心交互（直线拖拽 / 折线多点编辑 / 键盘快捷键）逐条保留，只是从「一个全局
// 可变对象 + 手动 DOM 操作」换成「每张卡一份 React state」。

const CL_KIND: Record<string, string> = { straight: '直线', seam_narrow: '窄走廊', seam_wide: '宽走廊' }

export function CutlinePanel({ book }: { book: string }) {
  const [pages, setPages] = useState('body')
  const [kind, setKind] = useState<'r2s' | 'split_char' | 'all'>('r2s')
  const [limit, setLimit] = useState(250)
  const [batchInput, setBatchInput] = useState('')
  const [onlyTodo, setOnlyTodo] = useState(true)
  const [cases, setCases] = useState<CutlineCase[]>([])
  const [msg, setMsg] = useState('')
  const [cur, setCur] = useState(0)
  // 每张卡的可变裁决状态；key = case.id。改动一张卡只影响它自己的 state 引用，
  // 不触发别的卡重渲染（cards 数组本身通过 version 计数强制父组件重渲染一次）。
  const cardState = useRef<Record<string, CardState>>({})
  const seenAt = useRef<Record<string, number>>({})
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const batch = () => {
    const suffix = kind === 'r2s' ? '' : '-' + kind
    return batchInput.trim() || `${book}-cutline${suffix}`
  }

  async function load() {
    const b = batch()
    setMsg('载入中…（首次要做整理本对齐，约一分钟）')
    let d
    try {
      d = await fetchCutlineCases(book, pages || 'body', limit || 250, b, onlyTodo, kind)
    } catch (e) {
      setMsg('失败：' + (e as Error).message)
      return
    }
    let done: Record<string, { verdict: string; y?: number; polyline?: Array<[number, number]>; cand?: string }> = {}
    try {
      done = (await fetchCutlineVerdicts(b)).verdicts || {}
    } catch {
      // 新批次，没有裁决可读，忽略
    }
    const next: Record<string, CardState> = {}
    const t0 = Date.now()
    for (const c of d.cases) {
      seenAt.current[c.id] = t0
      const st: CardState = { y: c.y, mode: 'line', poly: [], pick: c.chosen ?? 0, tags: {}, done: undefined, hidden: false }
      const dv = done[c.id]
      if (dv) {
        st.done = dv.verdict
        if (dv.y != null) st.y = dv.y
        if (dv.polyline) { st.poly = dv.polyline; st.mode = 'poly' }
        if (dv.cand) {
          const k = (c.candidates || []).findIndex((x) => x.kind === dv.cand)
          if (k >= 0) st.pick = k
        }
        st.hidden = onlyTodo
      }
      next[c.id] = st
    }
    cardState.current = next
    setCases(d.cases)
    setCur(0)
    const kindName = { r2s: '粘连 R2s', split_char: '切进字里', all: '粘连+切进字里' }[kind] || 'R2s'
    setMsg(`本册${kindName}共 ${d.n_r2s} 条，已有金标/已裁 ${d.n_done}，本次载入 ${d.n} 条 → 批次 ${b}`)
  }

  function focus(i: number) {
    if (!cases.length) return
    const dir = i >= cur ? 1 : -1
    let j = Math.max(0, Math.min(i, cases.length - 1))
    while (j >= 0 && j < cases.length) {
      const st = cardState.current[cases[j].id]
      if (!st || !st.hidden) break
      j += dir
    }
    if (j < 0 || j >= cases.length) j = Math.max(0, Math.min(i, cases.length - 1))
    setCur(j)
    document.getElementById(`clc${j}`)?.scrollIntoView({ block: 'nearest' })
  }

  function setY(i: number, y: number) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    if (!st) return
    st.y = Math.max(c.crop_y0 + 1, Math.min(c.crop_y1 - 1, Math.round(y)))
    bump()
  }

  function toggleTag(i: number, t: string) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    st.tags[t] = !st.tags[t]
    bump()
  }

  function pick(i: number, k: number) {
    const c = cases[i]
    if (!c) return
    cardState.current[c.id].pick = k
    bump()
    const cd = c.candidates[k]
    setMsg(k === 0 ? '选的是「直线」——落定请用「落定 / 现切点正确」'
      : `选了「${CL_KIND[cd?.kind ?? ''] || ''}」，按 C 或点「切法正确」落定`)
  }

  function toggleMode(i: number) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    st.mode = st.mode === 'poly' ? 'line' : 'poly'
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

  function popPoint(i: number) {
    const c = cases[i]
    if (!c) return
    cardState.current[c.id].poly.pop()
    bump()
  }

  function clearPoly(i: number) {
    const c = cases[i]
    if (!c) return
    cardState.current[c.id].poly = []
    bump()
  }

  function reopen(i: number) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    st.done = undefined
    st.hidden = false
    bump()
    focus(i)
    setMsg(`${c.id} 已重开，改完再落定（后到覆盖）`)
  }

  async function decide(i: number, verdictIn: string) {
    const c = cases[i]
    if (!c) return
    const st = cardState.current[c.id]
    let verdict = verdictIn
    let y = st.y
    if (verdict === 'moved' && y === c.y) verdict = 'ok'
    if (verdict === 'ok') y = c.y

    const tags = Object.keys(st.tags).filter((t) => st.tags[t])
    let polyline: Array<[number, number]> | undefined
    let cand: string | undefined

    if (verdict === 'seam_ok') {
      if (!c.seam || !c.seam.length) { setMsg('这条格线没有现役折线缝（绿虚线），用直线口径落定'); return }
      const step = 6
      polyline = []
      for (let k = 0; k < c.seam.length; k += step) polyline.push([c.x0 + k, c.seam[k]])
      if ((c.seam.length - 1) % step) polyline.push([c.x0 + c.seam.length - 1, c.seam[c.seam.length - 1]])
      y = Math.round(c.seam.reduce((a, q) => a + q, 0) / c.seam.length)
    } else if (verdict === 'cand') {
      const k = st.pick
      const cd = c.candidates[k]
      if (!cd || !cd.y || !cd.y.length) { setMsg('选中的是「直线」，用「落定 / 现切点正确」'); return }
      cand = cd.kind
      const step = 6
      polyline = []
      for (let j = 0; j < cd.y.length; j += step) polyline.push([c.x0 + j, cd.y[j]])
      if ((cd.y.length - 1) % step) polyline.push([c.x0 + cd.y.length - 1, cd.y[cd.y.length - 1]])
      y = Math.round(cd.y.reduce((a, q) => a + q, 0) / cd.y.length)
    } else if (st.mode === 'poly') {
      const pts = st.poly.slice().sort((a, b) => a[0] - b[0])
      if (pts.length < 2) { setMsg('折线模式至少要点 2 个点（Backspace 撤点，P 切回直线）'); return }
      polyline = pts
      y = Math.round(pts.reduce((a, q) => a + q[1], 0) / pts.length)
      if (verdict === 'ok') verdict = 'moved'
    }

    const now = Date.now()
    const row = {
      id: c.id, y, y_old: c.y, verdict, bi: c.bi, slot_above: c.slot_above, slot_below: c.slot_below,
      col_h: c.col_h, char_above: c.char_above || '', char_below: c.char_below || '',
      tags: tags.length ? tags : undefined, polyline, cand,
      client_ts: now, dwell_ms: seenAt.current[c.id] ? now - seenAt.current[c.id] : undefined,
    }
    st.done = verdict
    if (onlyTodo) st.hidden = true
    bump()
    try {
      await postEvents({ batch: batch(), step: 'row_segment', unit: 'boundary', kind: 'cutline', events: [row] })
      const n = Object.values(cardState.current).filter((s) => s.done).length
      setMsg(`已落 ${n} / ${cases.length} 条 → 批次 ${batch()}`)
    } catch (e) {
      setMsg('写入失败：' + (e as Error).message)
      st.done = undefined
      st.hidden = false
      bump()
      return
    }
    focus(i + 1)
  }

  // 键盘快捷键：只在本面板挂载时生效（v1 靠 #view-cutline.active 判断，
  // v2 里这个面板本来就只在 Step3 页面挂载，所以不需要再判断"当前视图"）。
  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      const c = cases[cur]
      if (!c) return
      const step = ev.shiftKey ? 5 : 1
      const st = cardState.current[c.id]
      if (ev.key === 'ArrowUp') { setY(cur, st.y - step); ev.preventDefault() }
      else if (ev.key === 'ArrowDown') { setY(cur, st.y + step); ev.preventDefault() }
      else if (ev.key === 'Enter') { decide(cur, 'moved'); ev.preventDefault() }
      else if (ev.key === 'o' || ev.key === 'O') { decide(cur, 'ok'); ev.preventDefault() }
      else if (ev.key === 'g' || ev.key === 'G') { decide(cur, 'seam_ok'); ev.preventDefault() }
      else if (ev.key === 'c' || ev.key === 'C') { decide(cur, 'cand'); ev.preventDefault() }
      else if (ev.key === 'v' || ev.key === 'V') { decide(cur, 'overlap'); ev.preventDefault() }
      else if (ev.key === 's' || ev.key === 'S') { decide(cur, 'idk'); ev.preventDefault() }
      else if (ev.key === 'ArrowRight' || ev.key === 'j') { focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 'ArrowLeft' || ev.key === 'k') { focus(cur - 1); ev.preventDefault() }
      else if (['1', '2', '3', '4'].includes(ev.key)) {
        toggleTag(cur, ['stain', 'border', 'residue', 'other'][+ev.key - 1]); ev.preventDefault()
      } else if (ev.key === 'p' || ev.key === 'P') { toggleMode(cur); ev.preventDefault() }
      else if (ev.key === 'Backspace') { popPoint(cur); ev.preventDefault() }
      else if (ev.key === 'x' || ev.key === 'X') { clearPoly(cur); ev.preventDefault() }
      else if (ev.key === 'u' || ev.key === 'U') { reopen(cur); ev.preventDefault() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cases, cur])

  return (
    <div className="card">
      <h2>拖切线 <span className="muted">粘连格线（R2s）：把横线拖到你认为该切的位置，攒成 touching-cuts 金标</span></h2>
      <div className="cl-toolbar">
        <label className="muted">页 <input value={pages} onChange={(e) => setPages(e.target.value)} size={10} title="body = 正文页；或 3-6,9" /></label>
        <label className="muted">类型
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}
                  title="r2s = 真粘连（切点有墨、无墨谷）；切进字里 = 一矮一高且切点落在字内部空隙">
            <option value="r2s">粘连 R2s</option>
            <option value="split_char">切进字里</option>
            <option value="all">两者</option>
          </select>
        </label>
        <label className="muted">条数 <input value={limit} onChange={(e) => setLimit(+e.target.value || 250)} size={4} /></label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册自动命名" /></label>
        <label className="muted"><input type="checkbox" checked={onlyTodo} onChange={(e) => setOnlyTodo(e.target.checked)} /> 只看未裁</label>
        <button onClick={load}>载入</button>
        <span className="muted">{msg}</span>
      </div>
      <p className="muted cl-help">
        在图上<b>点击或拖动</b>定位；键盘：<b>↑/↓</b> 1px（Shift 5px）· <b>回车</b> 落定（没动过 = 现切点正确）·
        <b>O</b> 现切点正确 · <b>G</b> 绿色折线缝已正确（直接记为折线金标）·
        <b>切法</b>（算法一次给几种切法时才有这一行，只读）：点一种选中它，<b>C</b> 记为该切法正确 · <b>V</b> 上下字重叠、切在哪都伤字（线放折中处）· <b>S</b> 拿不准 · <b>←/→</b> 翻卡 ·
        干扰标签 <b>1</b> 污点 <b>2</b> 界行/版框 <b>3</b> 邻字残墨 <b>4</b> 其他（落定前点，可多选；评测里分开算）。
        <b>P</b> 折线模式：点空白处加点，<b>点中已有点可拖动</b>，<b>右键</b>删点，<b>Backspace</b> 撤最后一点，<b>X</b> 清空，回车落定；
        <b>U</b> 重做已落定的卡。蓝色虚线 = 现役直线切点，绿色虚线 = 现役折线缝，
        蓝点虚线 = 窄走廊候选，黄点虚线 = 宽走廊候选。每次落定立刻写入事件，刷新不丢。
      </p>
      <div className="clgrid">
        {cases.map((c, i) => {
          const st = cardState.current[c.id]
          if (!st) return null
          if (st.hidden) return null
          return (
            <CutlineCard
              key={c.id} idx={i} c={c} st={st} isCurrent={i === cur}
              onFocus={() => focus(i)}
              onSetY={(y) => setY(i, y)}
              onAddPoint={(x, y) => addPoint(i, x, y)}
              onMovePoint={(k, x, y) => movePoint(i, k, x, y)}
              onRemovePoint={(k) => removePoint(i, k)}
              onDecide={(v) => decide(i, v)}
              onPick={(k) => pick(i, k)}
              onToggleMode={() => toggleMode(i)}
              onClearPoly={() => clearPoly(i)}
              onReopen={() => reopen(i)}
              onToggleTag={(t) => toggleTag(i, t)}
            />
          )
        })}
      </div>
    </div>
  )
}
