import { useEffect, useRef, useState } from 'react'
import { fetchAroundBatch, fetchRareBatch, fetchRareOne, fetchReviewCards, fetchReviewVerdicts, contextImgUrl } from '../../api/review'
import { postEvents } from '../../api/events'
import { needsReading, readingOf, consumedMsg } from '../../domain'
import type { AroundContext, RareCandidate, ReviewCard } from '../../types/review'
import { keyList } from './candidates'
import { ReviewCardView } from './ReviewCardView'
import './review.css'

// 迁移自 v1 static/js/panels/review.js（549 行，方案 §四标注"改造复用（分文件）"）。
// 一条口径（用户 2026-09-04 定）：先读字形，文本录入按文意，记录转换。
// 候选生成/键位表抽成纯函数（candidates.ts），交互与状态留在本组件。

export interface Verdict {
  shape: string
  reading: string
  done: string
  ts?: number
  dwell?: number
  noGlyphLib?: boolean
}

const PREFETCH_CHUNK = 24

export function ReviewPanel({ book, pages, onSubmitted, reloadSignal }: {
  book: string; pages: string; onSubmitted: () => void; reloadSignal?: number
}) {
  const [only, setOnly] = useState<'review' | 'auto' | 'all'>('review')
  const [batchInput, setBatchInput] = useState('')
  const [todoOnly, setTodoOnly] = useState(false)
  const [gate, setGate] = useState(true)
  const [cards, setCards] = useState<ReviewCard[]>([])
  const [cur, setCur] = useState(0)
  const [msg, setMsg] = useState('')
  const [gateNote, setGateNote] = useState<{ n: number } | null>(null)
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const verdicts = useRef<Record<string, Verdict>>({})
  const seen = useRef<Record<string, number>>({})
  const rare = useRef<Record<string, RareCandidate[]>>({})
  const rareFly = useRef<Set<string>>(new Set())
  const rareBusy = useRef(false)
  const rareWant = useRef<number | null>(null)
  const snapshot = useRef<Set<string> | null>(null)
  const around = useRef<Record<string, AroundContext>>({})
  const ctxImgOpen = useRef<Record<number, boolean>>({})
  const rareOut = useRef<Record<number, RareCandidate[] | 'loading' | 'error' | undefined>>({})

  const batch = () => batchInput.trim() || `${book}-${pages || 'dev_set'}-decide`

  async function load() {
    setMsg('载入中…')
    const b = batch()
    const d = await fetchReviewCards(book, pages || 'dev_set', only, gate)
    let done: Record<string, Verdict> = {}
    try {
      done = (await fetchReviewVerdicts(b)).verdicts || {}
    } catch {
      // 批次还不存在就是没裁过
    }
    verdicts.current = { ...done, ...verdicts.current }
    rare.current = {}
    rareFly.current = new Set()
    snapshot.current = null
    setCards(d.cards)
    setCur(0)
    const t0 = Date.now()
    d.cards.forEach((c) => { if (!seen.current[c.id]) seen.current[c.id] = t0 })
    const nb = (d.blocked || []).length
    setGateNote(nb ? { n: nb } : null)
    filterMsg(d.cards)
    focus(0, d.cards)

    fetchAroundBatch(book, 10, 10, d.cards.map((c) => ({ page: c.page, col: c.col, slot: c.slot })))
      .then((r) => { around.current = r.around || {}; bump() })
      .catch(() => {})
  }

  function filterMsg(list: ReviewCard[]) {
    const todo = todoOnly
    if (todo && !snapshot.current) {
      snapshot.current = new Set(list.filter((c) => !(verdicts.current[c.id] && verdicts.current[c.id].done)).map((c) => c.id))
    }
    if (!todo) snapshot.current = null
    const n = list.length
    const st = (c: ReviewCard) => verdicts.current[c.id]?.done
    const nDone = list.filter((c) => st(c) && st(c) !== 'need_reading').length
    const nNeed = list.filter((c) => st(c) === 'need_reading').length
    const shown = todo && snapshot.current ? list.filter((c) => snapshot.current!.has(c.id)).length : n
    setMsg(`${n} 张 · 已裁 ${nDone}` + (nNeed ? ` · 待填文意 ${nNeed}` : '') + (todo ? ` · 本轮待裁 ${shown}` : ''))
    bump()
  }

  function isHidden(c: ReviewCard): boolean {
    return !!(todoOnly && snapshot.current && !snapshot.current.has(c.id))
  }

  function focus(i: number, list?: ReviewCard[]) {
    const arr = list ?? cards
    if (!arr.length) return
    const dir = i >= cur ? 1 : -1
    let j = Math.max(0, Math.min(i, arr.length - 1))
    while (j >= 0 && j < arr.length) {
      if (!isHidden(arr[j])) break
      j += dir
    }
    if (j < 0 || j >= arr.length) j = Math.max(0, Math.min(i, arr.length - 1))
    setCur(j)
    document.getElementById(`rvc${j}`)?.scrollIntoView({ block: 'nearest' })
    prefetchRare(j, arr)
  }

  async function prefetchRare(i: number, list?: ReviewCard[]) {
    const arr = list ?? cards
    rareWant.current = i
    if (rareBusy.current) return
    rareBusy.current = true
    try {
      for (;;) {
        const c0 = rareWant.current ?? cur
        rareWant.current = null
        const taken: Array<{ j: number; c: ReviewCard }> = []
        for (let d = 0; d < arr.length && taken.length < PREFETCH_CHUNK; d++) {
          for (const j of d ? [c0 + d, c0 - d] : [c0]) {
            const c = arr[j]
            if (c && rare.current[c.id] === undefined && !rareFly.current.has(c.id)) {
              rareFly.current.add(c.id)
              taken.push({ j, c })
            }
          }
        }
        if (!taken.length) return
        try {
          const d = await fetchRareBatch(book, 3, taken.map(({ c }) => `${c.page}:${c.col}:${c.slot}${c.sub || ''}`))
          for (const { c } of taken) {
            rare.current[c.id] = d.rare[`${c.page}:${c.col}:${c.slot}${c.sub || ''}`] || []
            rareFly.current.delete(c.id)
          }
          bump()
        } catch {
          for (const { c } of taken) { rare.current[c.id] = []; rareFly.current.delete(c.id) }
        }
      }
    } finally {
      rareBusy.current = false
    }
  }

  function setVerdict(i: number, shape: string, reading?: string, doneIn?: string) {
    const c = cards[i]
    if (!c) return
    let mark = doneIn === undefined ? (shape ? '1' : '') : doneIn
    const rd = reading || ''
    if (needsReading(shape) && !rd) mark = 'need_reading'
    const prev = verdicts.current[c.id]
    const now = Date.now()
    const dwell = prev?.dwell !== undefined ? prev.dwell : (seen.current[c.id] ? now - seen.current[c.id] : undefined)
    const prevNoGlyphLib = verdicts.current[c.id]?.noGlyphLib
    verdicts.current[c.id] = {
      shape, reading: needsReading(shape) ? rd : (rd || shape),
      done: mark, ts: now, dwell, noGlyphLib: prevNoGlyphLib,
    }
    bump()
  }

  function setNoGlyphLib(i: number, checked: boolean) {
    const c = cards[i]
    if (!c) return
    const v = verdicts.current[c.id] || { shape: '', reading: '', done: '' }
    verdicts.current[c.id] = { ...v, noGlyphLib: checked }
    bump()
  }

  async function toggleCtxImg(i: number) {
    ctxImgOpen.current[i] = !ctxImgOpen.current[i]
    bump()
  }

  async function fetchRareFor(i: number, force?: boolean) {
    const c = cards[i]
    if (!c) return
    if (!force && rareOut.current[i] !== undefined) return
    rareOut.current[i] = 'loading'
    bump()
    try {
      const d = await fetchRareOne(book, c.page, c.col, c.slot, c.sub)
      rareOut.current[i] = d.candidates || []
    } catch {
      rareOut.current[i] = 'error'
    }
    bump()
  }

  async function submit() {
    const b = batch()
    const rows: Array<Record<string, unknown>> = []
    let pending = 0
    for (const [id, v] of Object.entries(verdicts.current)) {
      if (v.done === 'need_reading') { pending++; continue }
      if (!v.done) continue
      if (v.done === 'skip') { rows.push({ id, v: 'skip' }); continue }
      if (v.done === 'non') { rows.push({ id, v: 'not_a_char' }); continue }
      if (v.done === 'truncated' || v.done === 'contaminated') {
        rows.push({ id, v: 'seg_defect', quality: v.done, shape: v.shape || '', reading: readingOf(v), client_ts: v.ts, dwell_ms: v.dwell })
        continue
      }
      rows.push({
        id, v: 'confirm', shape: v.shape, reading: readingOf(v),
        conversion: readingOf(v) !== v.shape ? 1 : 0,
        no_glyph_lib: !!v.noGlyphLib,
        client_ts: v.ts, dwell_ms: v.dwell,
      })
    }
    if (pending) {
      setMsg(`有 ${pending} 张选了 己/已/巳 但没填文意（黄框那些），填完再提交`)
      const first = cards.findIndex((c) => verdicts.current[c.id]?.done === 'need_reading')
      if (first >= 0) focus(first)
      return
    }
    if (!rows.length) { setMsg('还没有裁决'); return }
    setMsg('提交中…')
    try {
      const r = await postEvents({ batch: b, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
      setMsg(`已写入 ${r.appended ?? rows.length} 条事件 → 批次 ${b}` + consumedMsg(r))
      onSubmitted()
    } catch (e) {
      setMsg('提交失败：' + (e as Error).message)
    }
  }

  // 外层（Step7「切分裁决」板块）裁完一条切分方案后 bump 这个信号，通知这里
  // 重新载入——刚被那条切线挡住的字卡才会跟着解锁。首次挂载不触发（还没人
  // 点过「载入」，没有 batch/verdicts 状态可续）。
  const reloadedOnce = useRef(false)
  useEffect(() => {
    if (reloadSignal === undefined) return
    if (!reloadedOnce.current) { reloadedOnce.current = true; return }
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadSignal])

  // `pages` 现在是 Step7 顶部统一页数选择区传下来的受控值（overview
  // 2026-09-11 下发）；切页时随之重新载入，跟点「载入」按钮等效。同样
  // 跳过首次挂载——初始页数由外层决定，不该一进页面就自动拉取。
  const pagesLoadedOnce = useRef(false)
  useEffect(() => {
    if (!pagesLoadedOnce.current) { pagesLoadedOnce.current = true; return }
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages])

  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      const c = cards[cur]
      if (!c) return
      if (ev.key === 'ArrowRight' || ev.key === 'j') { focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 'ArrowLeft' || ev.key === 'k') { focus(cur - 1); ev.preventDefault() }
      else if (['1', '2', '3', '4', '5'].includes(ev.key)) {
        const pick = keyList(c, rare.current[c.id]).find((e) => e.keys.includes(+ev.key))
        if (pick && pick.ch) { setVerdict(cur, pick.ch); focus(cur + 1); ev.preventDefault() }
      } else if (ev.key === 'n' || ev.key === 'N') { setVerdict(cur, '', '', 'non'); focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 's' || ev.key === 'S') { setVerdict(cur, '', '', 'skip'); focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 't' || ev.key === 'T') { setVerdict(cur, '', '', 'truncated'); focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 'c' || ev.key === 'C') { setVerdict(cur, '', '', 'contaminated'); focus(cur + 1); ev.preventDefault() }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards, cur])

  return (
    <div className="card">
      <h2>定字裁决 <span className="muted">待审字位就在这里裁，不必再发外部 artifact</span></h2>
      <div className="rv-toolbar">
        <label className="muted">范围
          <select value={only} onChange={(e) => setOnly(e.target.value as typeof only)}>
            <option value="review">只看待审</option>
            <option value="auto">抽查自动档</option>
            <option value="all">全部</option>
          </select>
        </label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册页自动命名" /></label>
        <label className="muted"><input type="checkbox" checked={todoOnly} onChange={(e) => { setTodoOnly(e.target.checked); snapshot.current = null; filterMsg(cards) }} /> 只看未裁决</label>
        <label className="muted" title="顺序闸：字位旁边那条切分线有多种切法且还没 review 时，这个字位先不出卡。取消勾选可整批看全部。">
          <input type="checkbox" checked={gate} onChange={(e) => setGate(e.target.checked)} /> 先切线后字符
        </label>
        <button onClick={load}>载入</button>
        <button onClick={submit}>提交裁决</button>
        <span className="muted">{msg}</span>
      </div>
      {gateNote && (
        <div className="muted rv-gate-note" style={{ color: 'var(--ochre)' }}>
          ⊘ {gateNote.n} 位被顺序闸挡下——它们的格线有<b>多种切法</b>还没 review。
        </div>
      )}
      <div className="rv-help">
        键盘：<b>1</b> 采信首选 · <b>2/3</b> 选次选 · <b>T</b> 字形不完整 · <b>C</b> 有噪声 ·
        <b>N</b> 非字 · <b>S</b> 跳过 · <b>←/→</b> 翻卡。
        字一律按图上刻的录。只有 <b>己 / 已 / 巳</b> 例外——它们史上本就混用，
        选中后会多出一个"文意"框，字形填图上的、文意填该读的；其余字不必区分。
      </div>
      <div className="rvgrid">
        {cards.map((c, i) => {
          if (isHidden(c)) return null
          return (
            <ReviewCardView
              key={c.id} idx={i} c={c} book={book} isCurrent={i === cur}
              verdict={verdicts.current[c.id]}
              keys={keyList(c, rare.current[c.id])}
              ctxImgOpen={!!ctxImgOpen.current[i]}
              aroundCtx={around.current[`${c.page}:${c.col}:${c.slot}`]}
              rareOut={rareOut.current[i]}
              onFocus={() => focus(i)}
              onSet={(shape: string, reading?: string, done?: string) => setVerdict(i, shape, reading, done)}
              onSetNoGlyphLib={(checked: boolean) => setNoGlyphLib(i, checked)}
              onToggleCtxImg={() => toggleCtxImg(i)}
              onFetchRare={(force?: boolean) => fetchRareFor(i, force)}
              contextImgSrc={contextImgUrl(book, c.page, c.col, c.slot)}
            />
          )
        })}
      </div>
    </div>
  )
}
