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
  // done === 'damaged' 时：人看图后「最像的那个字」，可空。
  // **不是 shape**——shape 会进字形库，guess 只进金标与文本层的括注 □（？塊）。
  guess?: string
}

const PREFETCH_CHUNK = 24

export function ReviewPanel({ book, pages, onSubmitted, reloadSignal }: {
  book: string; pages: string; onSubmitted: () => void; reloadSignal?: number
}) {
  const [only, setOnly] = useState<'review' | 'auto' | 'all'>('review')
  // 一屏能裁完的量（与 Step3 切分裁决同一个口径与缺省值，用户 2026-09-16）：
  // 一次拉 400 张人看不过来，滚到后面也累得裁不准了。大批量再手改。
  const [limit, setLimit] = useState(30)
  const [batchInput, setBatchInput] = useState('')
  // 「含已裁决」（用户 2026-09-16）：默认关 = 后端只出全书从未裁过的字位，
  // 于是「条数」数的是**净新卡**。以前是「载入 N 张，再在前端把已裁的隐藏掉」，
  // 每次都从第一页重数——实测 bxgb 载入 30 张里 30 张全是裁过的，净新卡为 0。
  const [inclDecided, setInclDecided] = useState(false)
  const [gate, setGate] = useState(true)
  const [cards, setCards] = useState<ReviewCard[]>([])
  const [cur, setCur] = useState(0)
  const [msg, setMsg] = useState('')
  const [gateNote, setGateNote] = useState<{ n: number } | null>(null)
  const [nDecided, setNDecided] = useState(0)   // 全书累计已裁字位数（后端跨批次去重后给的）
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const verdicts = useRef<Record<string, Verdict>>({})
  // 本轮人**真正动过**的字位。`verdicts.current` 里还混着从服务端读回的历史裁决，
  // 提交时若不区分，就会把没改的也重写一遍（见 `submit` 里的注释）。
  const touched = useRef<Set<string>>(new Set())
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

  // `scrollOnLoad=false`：外部信号（切分裁决联动、切页）触发的静默刷新——
  // 只更新数据，不把页面滚去「定字裁决」区域。用户 2026-09-11 实测踩到：
  // 每次在「切分裁决」落定一条，画面会被强行跳到定字裁决第一张卡，打断
  // 正在做的操作。手动点「载入」按钮才应该滚（那是用户主动要看结果）。
  async function load(scrollOnLoad = true) {
    setMsg('载入中…')
    const b = batch()
    const d = await fetchReviewCards(book, pages || 'dev_set', only, gate, limit || 30, !inclDecided)
    let done: Record<string, Verdict> = {}
    try {
      done = (await fetchReviewVerdicts(b)).verdicts || {}
    } catch {
      // 批次还不存在就是没裁过
    }
    verdicts.current = { ...done, ...verdicts.current }
    // 注意**不清** `touched`：静默刷新（切线联动 reloadSignal）会走到这里，
    // 而此时人可能已裁了几张还没提交，清掉就等于把这几张的裁决静默丢了。
    // 已提交的在 `submit` 里逐条移除，留在这里的都是真·未落盘。
    rare.current = {}
    rareFly.current = new Set()
    snapshot.current = null
    setCards(d.cards)
    setCur(0)
    const t0 = Date.now()
    d.cards.forEach((c) => { if (!seen.current[c.id]) seen.current[c.id] = t0 })
    const nb = (d.blocked || []).length
    setGateNote(nb ? { n: nb } : null)
    const nDec = d.n_decided || 0
    setNDecided(nDec)
    filterMsg(d.cards, nDec)
    focus(0, d.cards, scrollOnLoad)

    fetchAroundBatch(book, 10, 10, d.cards.map((c) => ({ page: c.page, col: c.col, slot: c.slot })))
      .then((r) => { around.current = r.around || {}; bump() })
      .catch(() => {})
  }

  // `nDec` 显式传入，不走 state：`load()` 里 setState 还没生效，闭包读到的是上一轮的值。
  function filterMsg(list: ReviewCard[], nDec = nDecided) {
    const n = list.length
    const st = (c: ReviewCard) => verdicts.current[c.id]?.done
    // 「已裁」= 本轮在这一屏里刚裁的。已裁过的卡默认压根不载入（后端 skip_decided），
    // 所以这个数从 0 涨到 n 就是本屏的进度条；`nDecided` 是全书累计，另计。
    const nDone = list.filter((c) => st(c) && st(c) !== 'need_reading').length
    const nNeed = list.filter((c) => st(c) === 'need_reading').length
    setMsg(`${n} 张 · 已裁 ${nDone}`
      + (nNeed ? ` · 待填文意 ${nNeed}` : '')
      + (nDec ? ` · 全书已裁 ${nDec}${inclDecided ? '（含在本屏）' : '，已跳过'}` : ''))
    bump()
  }

  // 卡片一律显示：该不出的在后端就没出。（旧版这里按 snapshot 在前端隐藏，
  // 是「先载入再藏」那套机制的残留，已随 skip_decided 废止。）
  function isHidden(_c: ReviewCard): boolean {
    return false
  }

  function focus(i: number, list?: ReviewCard[], scroll = true) {
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
    if (scroll) document.getElementById(`rvc${j}`)?.scrollIntoView({ block: 'nearest' })
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

  function prevDone(id: string): string {
    return verdicts.current[id]?.done || ''
  }

  function setVerdict(i: number, shape: string, reading?: string, doneIn?: string) {
    const c = cards[i]
    if (!c) return
    // 从候选/输入框改字时（doneIn 省略）：切分缺陷两档要**保住**，别被改字顶掉——
    // 「这块图切坏了」与「这是哪个字」是两件事，可以同时成立（用户 2026-09-20）。
    const keepDefect = (doneIn === undefined
                        && (prevDone(c.id) === 'truncated' || prevDone(c.id) === 'contaminated'))
    let mark = doneIn === undefined ? (keepDefect ? prevDone(c.id) : (shape ? '1' : '')) : doneIn
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
    touched.current.add(c.id)
    bump()
  }

  function setGuess(i: number, guess: string) {
    const c = cards[i]
    if (!c) return
    const v = verdicts.current[c.id] || { shape: '', reading: '', done: '' }
    verdicts.current[c.id] = { ...v, guess }
    touched.current.add(c.id)
    bump()
  }

  function setNoGlyphLib(i: number, checked: boolean) {
    const c = cards[i]
    if (!c) return
    const v = verdicts.current[c.id] || { shape: '', reading: '', done: '' }
    verdicts.current[c.id] = { ...v, noGlyphLib: checked }
    touched.current.add(c.id)
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
      // 只发**本轮真正动过的**（用户 2026-09-16「反复 confirm 要合并，只记后面的」）。
      // `verdicts.current` 里混着 `load()` 从服务端读回的历史裁决（`{...done, ...current}`），
      // 以前整个 Object.entries 一股脑提交，于是每点一次「提交裁决」就把全部历史
      // 原样重写一遍——实测 bxgb 1620 条 confirm 只覆盖 312 个字位，批次之间完全
      // 包含，`bxgb:3:1:19` 累计写了 13 次。重放语义（后到覆盖）一直是对的，
      // 错的是**每次都把没改的也写进去**。`touched` 由裁决动作登记，见 `mark()`。
      if (!touched.current.has(id)) continue
      if (v.done === 'skip') { rows.push({ id, v: 'skip' }); continue }
      if (v.done === 'damaged') {
        // 原图破损：字形不可辨，文本层出 □。`guess` 是括注用的「最像哪个字」，
        // 可空；不进字形库（后端 glyphdb_admit 只认 v==='confirm'）。
        rows.push({ id, v: 'damaged', guess: v.guess || '', client_ts: v.ts, dwell_ms: v.dwell })
        continue
      }
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
      // 已落盘的不再算「动过」——否则下次提交又把它们重写一遍，重复照旧。
      // 只清本次提交的这批：提交是 await 的，其间人可能已经裁了新卡。
      for (const row of rows) touched.current.delete(row.id as string)
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
    load(false)   // 静默刷新，不抢用户在切分裁决那边的操作焦点
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
      // D = 原图破损。**不自动跳下一张**：人多半要接着在「最像」框里填一个字。
      else if (ev.key === 'd' || ev.key === 'D') { setVerdict(cur, '', '', 'damaged'); ev.preventDefault() }
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
        <label className="muted" title="一次载入多少张卡。缺省 30 = 一屏能裁完的量；调大再按「重新载入」。">
          条数 <input value={limit} onChange={(e) => setLimit(+e.target.value || 30)} size={4} />
        </label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册页自动命名" /></label>
        <label className="muted" title="默认只出全书从未裁过的字位（跨批次去重），所以「条数」数的是净新卡。勾上则把已裁过的也一并载入——复核自己裁过的、或想改主意时用。">
          <input type="checkbox" checked={inclDecided} onChange={(e) => setInclDecided(e.target.checked)} /> 含已裁决
        </label>
        <label className="muted" title="顺序闸：字位旁边那条切分线有多种切法且还没 review 时，这个字位先不出卡。取消勾选可整批看全部。">
          <input type="checkbox" checked={gate} onChange={(e) => setGate(e.target.checked)} /> 先切线后字符
        </label>
        <button onClick={() => load()}>载入</button>
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
        <b>N</b> 非字 · <b>S</b> 跳过 · <b>D</b> 原图破损 · <b>←/→</b> 翻卡。
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
              onSetGuess={(g: string) => setGuess(i, g)}
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
