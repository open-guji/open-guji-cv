import { useEffect, useRef, useState } from 'react'
import { aroundKey, fetchAroundBatch, fetchRareBatch, fetchRareOne, fetchReviewCards, fetchReviewVerdicts, contextImgUrl } from '../../api/review'
import { postEvents } from '../../api/events'
import { consumedMsg } from '../../domain'
import type { AroundContext, RareCandidate, ReviewCard, ReviewClassMeta } from '../../types/review'
import { aiAccepted, defaultShape } from './ai'
import { keyList } from './candidates'
import { ReviewCardView } from './ReviewCardView'
import { occludedDefault, occludedGroupRows, staleDefault } from './doubt'
import { CLASS_HELP, classHelpKey, DEFAULT_HELP, countShadowPre, dropOffScreen, gridFlagRows, gridRows, isJysCard, JYS_NONE_KEYS, jysPickByKey,
         keepApprox, nextGridState, pickVerdict, screenRows } from './reviewClass'
import type { GridState } from './reviewClass'
import { ReplaceAlignGrid } from './ReplaceAlignGrid'
import './review.css'

// 迁移自 v1 static/js/panels/review.js（549 行，方案 §四标注"改造复用（分文件）"）。
// 一条口径（用户 2026-09-26 定）：每一格只裁一个字，就是字形；没有「读法」。
// 候选生成/键位表抽成纯函数（candidates.ts），交互与状态留在本组件。
//
// 按类别审（overview#247，2026-09-28）：层级 = 范围 → **类别**（主导航，点了就载入，按钮上是
// 这一类还剩几张）→ 本类细项（条数、含已裁决、先切线后字符、批次，默认收起）。队列模式：
// 提交后自动载入同一类的下一批。一张卡只归优先级最高的一类（后端 `REVIEW_CLASSES`）；
// 卡片样式与快捷键跟着类别走（`reviewClass.ts`，己已巳是三选一专用卡）。
//
// 对齐改字层分细项（overview#265）：网格（缺省，一屏几十张缺省采信整理本，只点掉异常的，
// `ReplaceAlignGrid`）／列尾（易混框线，逐张）／逐张（形近疑因、整理本空或惯刻形不同）。
// 细项划分的正本在后端 `review/cards.py::replace_align_sub`。

export interface Verdict {
  shape: string
  done: string
  ts?: number
  dwell?: number
  noGlyphLib?: boolean
  // done === 'damaged' 时：人看图后「最像的那个字」，可空。
  // **不是 shape**——shape 会进字形库，guess 只进金标与文本层的括注 □（？塊）。
  guess?: string
  // 无匹配（近似字，overview#276）：Unicode 里没有真正对应的字，shape 只是字形最像、意思最近的。
  // 勾上才展开 IDS／备注；事件 payload 多带 approx/ids/note（`reviewClass.approxFields`）。
  approx?: boolean
  approxIds?: string
  approxNote?: string
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
  // 按类别审（overview#247）：'' = 还没选（首次载入发 `*`，只为拿计数画导航）；'*' = 全部类别混着；
  // 其余 = 某一类。请求一律带 `cls`——按钮上的数是「这一类一共还剩几张」（不受「条数」截断）。
  // （原 #215 的 doubt 码筛选后端仍在，面板改用类别：一张卡多个码时按码筛会在几个按钮下各出一次。）
  const [cls, setCls] = useState('')
  const [classCounts, setClassCounts] = useState<Record<string, number> | null>(null)
  const [classTotal, setClassTotal] = useState(0)
  const [classes, setClasses] = useState<ReviewClassMeta[]>([])
  // 上下文缺省显示整理本对位原文；勾上才显示刻本那边的读法（#247）
  const [ctxKeben, setCtxKeben] = useState(false)
  const [groupBusy, setGroupBusy] = useState(false)
  // 对齐改字层的细项（overview#265）：只在 cls === 'replace_align' 时有意义
  const [raSub, setRaSub] = useState<'grid' | 'tail' | 'manual'>('grid')
  const [subCounts, setSubCounts] = useState<Record<string, number> | null>(null)
  const [subMeta, setSubMeta] = useState<ReviewClassMeta[]>([])
  const [gridN, setGridN] = useState(60)
  // 影子预勾（overview#269）：缺省开；后端没有预测文件时（`shadow_info.available=false`）自动禁用
  const [useShadow, setUseShadow] = useState(true)
  const [shadowAvail, setShadowAvail] = useState(false)
  const [gridCards, setGridCards] = useState<ReviewCard[]>([])
  const [gridStates, setGridStates] = useState<Record<string, GridState>>({})
  const gridSeen = useRef<number | undefined>(undefined)
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const verdicts = useRef<Record<string, Verdict>>({})
  // 本轮人**真正动过**的字位。`verdicts.current` 里还混着从服务端读回的历史裁决，
  // 提交时若不区分，就会把没改的也重写一遍（见 `submit` 里的注释）。
  const touched = useRef<Set<string>>(new Set())
  // touched 里哪些是 `load()` 预填默认裁决登记的（印章遮挡默认、AI／CNN 预选），人一动就摘掉。
  // 切换类别时这些悄悄丢，人亲手点过的丢了要报条数（#265 补丁，见 reviewClass `dropOffScreen`）。
  const autoTouched = useRef<Set<string>>(new Set())
  const seen = useRef<Record<string, number>>({})
  const rare = useRef<Record<string, RareCandidate[]>>({})
  const rareFly = useRef<Set<string>>(new Set())
  const rareBusy = useRef(false)
  const rareWant = useRef<number | null>(null)
  const snapshot = useRef<Set<string> | null>(null)
  const around = useRef<Record<string, AroundContext>>({})
  const ctxImgOpen = useRef<Record<number, boolean>>({})
  const rareOut = useRef<Record<number, RareCandidate[] | 'loading' | 'error' | undefined>>({})
  // 己已巳卡点了「都不是」的格 → 展开成普通卡
  const jysOpen = useRef<Record<string, boolean>>({})

  const batch = () => batchInput.trim() || `${book}-${pages || 'dev_set'}-decide`

  // `scrollOnLoad=false`：外部信号（切分裁决联动、切页）触发的静默刷新——
  // 只更新数据，不把页面滚去「定字裁决」区域。用户 2026-09-11 实测踩到：
  // 每次在「切分裁决」落定一条，画面会被强行跳到定字裁决第一张卡，打断
  // 正在做的操作。手动点「载入」按钮才应该滚（那是用户主动要看结果）。
  async function load(scrollOnLoad = true, sel = cls, sub = raSub, shadowOn = useShadow) {
    setMsg('载入中…')
    const b = batch()
    const ra = sel === 'replace_align'
    const gridMode = ra && sub === 'grid'
    const t0load = performance.now()
    // 网格缺省采信，**永远不出已裁过的格**（「含已裁决」在网格里不生效）：否则整屏一提交就把
    // 以前的裁决静默改成整理本字。
    const d = await fetchReviewCards(book, pages || 'dev_set', only, gate,
                                     gridMode ? (gridN || 60) : (limit || 30), gridMode || !inclDecided,
                                     '', sel || '*', ra ? sub : '', shadowOn)
    setClassCounts(d.class_counts ?? null)
    setClassTotal(d.class_total ?? 0)
    if (d.classes) setClasses(d.classes)
    setShadowAvail(!!d.shadow_info?.available)
    setSubCounts(d.class_sub_counts?.replace_align ?? null)
    if (d.class_subs?.replace_align) setSubMeta(d.class_subs.replace_align)
    // 切换类别／细项（#265 补丁）：上一屏没提交的裁决不带到新一屏——不在新一屏上的 touched 全丢，
    // 连同本地裁决一起丢（否则卡再出现时显示着旧裁决、却不算动过，提交时又漏掉）。
    // 静默刷新（同类别、切线联动 / 切页）不丢；那些卡不在屏上时提交也不会带上（`screenRows`）。
    let dropNote = ''
    if (sel !== cls || (ra && sub !== raSub)) {
      const keep = new Set(gridMode ? [] : d.cards.map((c) => c.id))
      const { dropped, human } = dropOffScreen(keep, touched.current, autoTouched.current)
      for (const id of dropped) {
        touched.current.delete(id)
        autoTouched.current.delete(id)
        delete verdicts.current[id]
      }
      if (human.length) dropNote = `；⚠ 切换时丢弃了上一屏 ${human.length} 张手动裁决（没提交）`
    }
    if (gridMode) {
      // 网格：每张缺省采信整理本。点过的档位按 id 留着**不清**——静默刷新（切线联动 reloadSignal）
      // 也走这里，清掉的话人点掉还没提交的格会退回「采信」，一提交就收了。提交成功的在 submitGrid 里摘。
      setGridCards(d.cards)
      gridSeen.current = Date.now()
      setCards([])
      setCur(0)
      setGateNote((d.blocked || []).length ? { n: (d.blocked || []).length } : null)
      setNDecided(d.n_decided || 0)
      setMsg(`网格 ${d.cards.length} 张（缺省采信整理本）· 载入 ${Math.round(performance.now() - t0load)} ms` + dropNote)
      return d
    }
    setGridCards([])
    let done: Record<string, Verdict> = {}
    try {
      done = (await fetchReviewVerdicts(b)).verdicts || {}
    } catch {
      // 批次还不存在就是没裁过
    }
    verdicts.current = { ...done, ...verdicts.current }
    // Step6-AI 默认预选（任务书-C-人审卡按AI预选，2026-09-27）：只对**这一格
    // 还没有任何裁决**（服务端没裁过、本地也没动过）且 AI 首组只有一个字的
    // 卡片生效——首组多个字时不替人选（`aiDefaultShape` 返回 null），组内
    // 字形仍由人看图点。视为「已裁」（标 touched）会跟着提交按钮走，人看图
    // 发现不对时点别的候选/输入框覆盖即可，跟人工选完再改主意的路径一样。
    for (const c of d.cards) {
      if (verdicts.current[c.id]) continue
      // 印章遮挡格（overview#195）：默认整理本字、字形不入库；假格（整理本空格位）默认「非字」
      if (c.occluded) {
        verdicts.current[c.id] = occludedDefault(c, Date.now()) ?? { shape: '', done: '', ts: Date.now(), noGlyphLib: true }
        if (verdicts.current[c.id].done) { touched.current.add(c.id); autoTouched.current.add(c.id) }
        continue
      }
      // 失效老裁决（overview#403 缺口 A）：人当时裁的字当预勾，比 AI／CNN 默认优先
      const sv = staleDefault(c, Date.now())
      if (sv) {
        verdicts.current[c.id] = sv
        touched.current.add(c.id)
        autoTouched.current.add(c.id)
        continue
      }
      // 借库书（`c.first`）没有 Step6-AI 默认时用 CNN／融合首选（defaultShape，2026-09-27）
      const def = defaultShape(c)
      if (!def) continue
      verdicts.current[c.id] = { shape: def, done: '1', ts: Date.now() }
      touched.current.add(c.id)
      autoTouched.current.add(c.id)
    }
    // 注意**不清** `touched`：静默刷新（切线联动 reloadSignal）会走到这里，
    // 而此时人可能已裁了几张还没提交，清掉就等于把这几张的裁决静默丢了。
    // 已提交的在 `submit` 里逐条移除，留在这里的都是真·未落盘。
    rare.current = {}
    rareFly.current = new Set()
    snapshot.current = null
    // 这两个按卡片**下标**记——换了一批卡，下标对应的格全变了，留着会串到别的卡上
    rareOut.current = {}
    ctxImgOpen.current = {}
    setCards(d.cards)
    setCur(0)
    const t0 = Date.now()
    d.cards.forEach((c) => { if (!seen.current[c.id]) seen.current[c.id] = t0 })
    const nb = (d.blocked || []).length
    setGateNote(nb ? { n: nb } : null)
    const nDec = d.n_decided || 0
    setNDecided(nDec)
    filterMsg(d.cards, nDec)
    if (dropNote) setMsg((m) => m + dropNote)
    focus(0, d.cards, scrollOnLoad)

    // 上下文前后各 20 字（可跨列跨页），一批卡一次请求（#247）
    fetchAroundBatch(book, 20, 20, d.cards.map((c) => ({ page: c.page, col: c.col, slot: c.slot, sub: c.sub || '' })))
      .then((r) => { around.current = r.around || {}; bump() })
      .catch(() => {})
    return d
  }

  // `nDec` 显式传入，不走 state：`load()` 里 setState 还没生效，闭包读到的是上一轮的值。
  function filterMsg(list: ReviewCard[], nDec = nDecided) {
    const n = list.length
    const st = (c: ReviewCard) => verdicts.current[c.id]?.done
    // 「已裁」= 本轮在这一屏里刚裁的。已裁过的卡默认压根不载入（后端 skip_decided），
    // 所以这个数从 0 涨到 n 就是本屏的进度条；`nDecided` 是全书累计，另计。
    const nDone = list.filter((c) => st(c)).length
    setMsg(`${n} 张 · 已裁 ${nDone}`
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
    // 「库里没有」这一类多半是生僻字：当前卡自动查 10 个候选（#247「卡片样式跟着类别变」）
    if (arr[j]?.cls === 'lib_miss') fetchRareFor(j, false, arr)
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

  function setVerdict(i: number, shape: string, doneIn?: string) {
    const c = cards[i]
    if (!c) return
    // 从候选/输入框改字时（doneIn 省略）：切分缺陷两档要**保住**，别被改字顶掉——
    // 「这块图切坏了」与「这是哪个字」是两件事，可以同时成立（用户 2026-09-20）。
    // 己已巳专用卡的三选一也走这条（doneIn 省略），与点普通卡的候选同一口径（`pickVerdict`）。
    const prev = verdicts.current[c.id]
    const now = Date.now()
    if (doneIn === undefined) {
      verdicts.current[c.id] = pickVerdict(shape, prev, seen.current[c.id], now)
    } else {
      const dwell = prev?.dwell !== undefined ? prev.dwell : (seen.current[c.id] ? now - seen.current[c.id] : undefined)
      verdicts.current[c.id] = { shape, done: doneIn, ts: now, dwell, noGlyphLib: prev?.noGlyphLib, ...keepApprox(prev) }
    }
    touched.current.add(c.id)
    autoTouched.current.delete(c.id)
    bump()
  }

  function setGuess(i: number, guess: string) {
    const c = cards[i]
    if (!c) return
    const v = verdicts.current[c.id] || { shape: '', done: '' }
    verdicts.current[c.id] = { ...v, guess }
    touched.current.add(c.id)
    autoTouched.current.delete(c.id)
    bump()
  }

  function setNoGlyphLib(i: number, checked: boolean) {
    const c = cards[i]
    if (!c) return
    const v = verdicts.current[c.id] || { shape: '', done: '' }
    verdicts.current[c.id] = { ...v, noGlyphLib: checked }
    touched.current.add(c.id)
    autoTouched.current.delete(c.id)
    bump()
  }

  /** 近似字勾选与 IDS／备注（overview#276）：`patch` 只含改了的键，其余沿用。 */
  function setApprox(i: number, patch: Pick<Verdict, 'approx' | 'approxIds' | 'approxNote'>) {
    const c = cards[i]
    if (!c) return
    const v = verdicts.current[c.id] || { shape: '', done: '' }
    verdicts.current[c.id] = { ...v, ...patch }
    touched.current.add(c.id)
    autoTouched.current.delete(c.id)
    bump()
  }

  async function toggleCtxImg(i: number) {
    ctxImgOpen.current[i] = !ctxImgOpen.current[i]
    bump()
  }

  async function fetchRareFor(i: number, force?: boolean, list?: ReviewCard[]) {
    const c = (list ?? cards)[i]
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
    if (cls === 'replace_align' && raSub === 'grid') return submitGrid()
    const b = batch()
    // 只收**当前屏上显示着的**卡（#265 补丁，`screenRows`）：`touched` 里可能还留着别的类别
    // 载入时预填的默认裁决（印章遮挡），以前会跟着这里静默提交。
    //
    // 只发**本轮真正动过的**（用户 2026-09-16「反复 confirm 要合并，只记后面的」）。
    // `verdicts.current` 里混着 `load()` 从服务端读回的历史裁决（`{...done, ...current}`），
    // 以前整个 Object.entries 一股脑提交，于是每点一次「提交裁决」就把全部历史
    // 原样重写一遍——实测 bxgb 1620 条 confirm 只覆盖 312 个字位，批次之间完全
    // 包含，`bxgb:3:1:19` 累计写了 13 次。重放语义（后到覆盖）一直是对的，
    // 错的是**每次都把没改的也写进去**。`touched` 由裁决动作登记，见 `setVerdict`。
    //
    // 「是否采纳 AI 预选」（任务书-C-人审卡按AI预选 §6）：`null` = 这一格
    // 没问过 AI（`card.ai` 缺失），不是「没采纳」——四庫等书这里恒是 null。
    // **2026-09-27 C 道暂拟字段名 `ai_accepted`，待与 H 道约定**（cross 单
    // 见 inbox/C-人审卡AI预选/），只加可选字段，不改 `confirm` 既有字段。
    const rows = screenRows(cards, verdicts.current, touched.current, (c, sh) => aiAccepted(c, sh))
    if (!rows.length) { setMsg('还没有裁决'); return }
    setMsg('提交中…')
    try {
      const r = await postEvents({ batch: b, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
      // 已落盘的不再算「动过」——否则下次提交又把它们重写一遍，重复照旧。
      // 只清本次提交的这批：提交是 await 的，其间人可能已经裁了新卡。
      for (const row of rows) { touched.current.delete(row.id as string); autoTouched.current.delete(row.id as string) }
      const done = `已写入 ${r.appended ?? rows.length} 条事件 → 批次 ${b}` + consumedMsg(r)
      onSubmitted()
      // 队列模式（#247）：提交完自动载入同一类的下一批。裁过的后端已跳过（skip_decided），
      // 这一屏没裁的会再出现；「含已裁决」开着时不自动翻（那是复核模式，翻了就看不到刚裁的）。
      if (cls && !inclDecided) {
        const d = await load(true, cls)
        const left = cls === '*' ? (d.class_total ?? 0) : (d.class_counts?.[cls] ?? 0)
        setMsg(`${done}；已载入本类下一批 ${d.cards.length} 张，本类还剩 ${left}`)
      } else {
        setMsg(done)
      }
    } catch (e) {
      setMsg('提交失败：' + (e as Error).message)
    }
  }

  function pickClass(key: string) {
    setCls(key)
    // 进「对齐改字层」缺省落在网格（overview#265）
    if (key === 'replace_align' && key !== cls) { setRaSub('grid'); load(true, key, 'grid'); return }
    load(true, key)
  }

  function pickSub(sub: 'grid' | 'tail' | 'manual') {
    setRaSub(sub)
    load(true, 'replace_align', sub)
  }

  function toggleGrid(id: string) {
    setGridStates((prev) => ({ ...prev, [id]: nextGridState(prev[id]) }))
  }

  // 网格整屏提交（overview#265）：没点的 = 采信，一格一行（普通卡按 1，行由 `gridRows`→`verdictRow` 出，
  // 与逐张裁决逐字段相同）；点了「要细审」的写 `needs_review`（`gridFlagRows`，不是裁决，格转到逐张）。
  // 两种 kind 分两次 `POST /api/events`。
  async function submitGrid() {
    if (!gridCards.length || groupBusy) { if (!gridCards.length) setMsg('这一屏没有卡'); return }
    const now = Date.now()
    const rows = gridRows(gridCards, gridStates, gridSeen.current, now, (c, sh) => aiAccepted(c, sh),
                          shadowAvail && useShadow)
    const flags = gridFlagRows(gridCards, gridStates, now, shadowAvail && useShadow)
    if (!rows.length && !flags.length) { setMsg('这一屏没有可提交的'); return }
    setGroupBusy(true)
    setMsg('提交中…')
    const b = batch()
    try {
      let appended = 0
      let r: Awaited<ReturnType<typeof postEvents>> | undefined
      if (rows.length) {
        r = await postEvents({ batch: b, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
        appended += r.appended ?? rows.length
      }
      if (flags.length) {
        const f = await postEvents({ batch: b, step: 'seed_admit', unit: 'cell', kind: 'needs_review',
                                     events: flags, consume: false })
        appended += f.appended ?? flags.length
      }
      const sent = new Set([...rows, ...flags].map((x) => x.id as string))
      setGridStates((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => !sent.has(id))))
      const done = `网格：已写入 ${appended} 条事件 → 批次 ${b}` + (r ? consumedMsg(r) : '')
        + `（采信 ${rows.length} · 要细审 ${flags.length}，已转到「逐张」）`
      onSubmitted()
      const d = await load(true, 'replace_align', 'grid')
      setMsg(`${done}；已载入下一屏 ${d.cards.length} 张，网格还剩 ${d.class_sub_counts?.replace_align?.grid ?? 0}`)
    } catch (e) {
      setMsg('网格提交失败：' + (e as Error).message)
    } finally {
      setGroupBusy(false)
    }
  }

  // 印章遮挡整组一键确认（overview#215 ②）：与 #166 按簇提交同一机制——展开成 N 条逐格事件，
  // 走既有 `POST /api/events`。先按 `doubt=occluded` 把**这一组全部**拉回来（不受「条数」
  // 截断），每格用人在屏上改过的裁决、没改过就用默认（整理本字／非字），字形一律不入库。
  async function confirmOccludedGroup() {
    const n = classCounts?.occluded || 0
    if (!n || groupBusy) return
    if (!window.confirm(`把 ${n} 格印章遮挡卡按默认（整理本字／整理本空位判非字）整组确认？\n`
      + '字形一律不入库；屏上改过的格按改过的提交。')) return
    setGroupBusy(true)
    setMsg('整组载入中…')
    try {
      const d = await fetchReviewCards(book, pages || 'dev_set', only, gate, Math.max(n, 1), !inclDecided, '', 'occluded')
      const { rows, skipped } = occludedGroupRows(d.cards, verdicts.current, Date.now())
      if (!rows.length) { setMsg(`这组 ${d.cards.length} 格都没有默认字，请逐格填`); return }
      const b = batch()
      const r = await postEvents({ batch: b, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
      for (const row of rows) { touched.current.delete(row.id as string); autoTouched.current.delete(row.id as string) }
      // 这组裁完了，停在「印章遮挡」只剩空屏——回到全部类别
      const next = cls === 'occluded' ? '*' : cls
      setCls(next)
      await load(false, next || '*')
      setMsg(`印章遮挡整组：已写入 ${r.appended ?? rows.length} 条事件 → 批次 ${b}` + consumedMsg(r)
        + (skipped.length ? `；${skipped.length} 格没有默认字，留在待审` : ''))
      onSubmitted()
    } catch (e) {
      setMsg('整组确认失败：' + (e as Error).message)
    } finally {
      setGroupBusy(false)
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

  // 范围是层级的第一层：换了范围，各类计数都变——已经载入过的话立刻按新范围重载（#247）。
  // 没载入过（`classCounts` 为空）不自动拉，与「切页不在首次挂载时自动载入」同一个理由。
  const onlyLoadedOnce = useRef(false)
  useEffect(() => {
    if (!onlyLoadedOnce.current) { onlyLoadedOnce.current = true; return }
    if (classCounts) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [only])

  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      const c = cards[cur]
      if (!c) return
      // 己已巳专用卡：1/2/3 = 己/已/巳，4/0 = 都不是（展开成普通卡）；T/C/D 这张卡上没有，不响应
      if (isJysCard(c.cls, !!jysOpen.current[c.id])) {
        const ch = jysPickByKey(ev.key)
        if (ch) { setVerdict(cur, ch); focus(cur + 1); ev.preventDefault(); return }
        if (JYS_NONE_KEYS.includes(ev.key)) { jysOpen.current[c.id] = true; bump(); ev.preventDefault(); return }
        if (/^[5tTcCdD]$/.test(ev.key)) return
      }
      if (ev.key === 'ArrowRight' || ev.key === 'j') { focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 'ArrowLeft' || ev.key === 'k') { focus(cur - 1); ev.preventDefault() }
      else if (['1', '2', '3', '4', '5'].includes(ev.key)) {
        const pick = keyList(c, rare.current[c.id]).find((e) => e.keys.includes(+ev.key))
        if (pick && pick.ch) { setVerdict(cur, pick.ch); focus(cur + 1); ev.preventDefault() }
      } else if (ev.key === 'n' || ev.key === 'N') { setVerdict(cur, '', 'non'); focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 's' || ev.key === 'S') { setVerdict(cur, '', 'skip'); focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 't' || ev.key === 'T') { setVerdict(cur, '', 'truncated'); focus(cur + 1); ev.preventDefault() }
      // Z = 小注当正文（overview#265）：字形不完整的一种，事件多带 reason=jiazhu_as_main
      else if (ev.key === 'z' || ev.key === 'Z') { setVerdict(cur, '', 'jiazhu'); focus(cur + 1); ev.preventDefault() }
      // M = 正文当小注（overview#415/#436）：反向，事件多带 reason=main_as_jiazhu
      else if (ev.key === 'm' || ev.key === 'M') { setVerdict(cur, '', 'main'); focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 'c' || ev.key === 'C') { setVerdict(cur, '', 'contaminated'); focus(cur + 1); ev.preventDefault() }
      // D = 原图破损。**不自动跳下一张**：人多半要接着在「最像」框里填一个字。
      else if (ev.key === 'd' || ev.key === 'D') { setVerdict(cur, '', 'damaged'); ev.preventDefault() }
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
        <button onClick={() => { const k = cls || '*'; setCls(k); load(true, k) }}
                title="按当前范围、类别重新载入；还没选类别时载入全部类别并给出各类计数">{classCounts ? '重新载入' : '载入'}</button>
        <button onClick={submit}
                title={cls && !inclDecided ? '提交这一屏的裁决，然后自动载入本类下一批' : '提交这一屏的裁决'}>提交裁决</button>
        <span className="muted">{msg}</span>
      </div>
      {classCounts && (
        <div className="rv-classes" data-testid="rv-classes">
          <span className="muted">类别</span>
          <button className={cls === '*' ? 'on' : ''} onClick={() => pickClass('*')}
                  title="不分类别，按页序混着出">全部<span className="n">{classTotal}</span></button>
          {classes.filter((m) => classCounts[m.key]).map((m) => (
            <button key={m.key} data-cls={m.key} className={cls === m.key ? 'on' : ''}
                    onClick={() => pickClass(m.key)} title={m.hint}>
              {m.label}<span className="n">{classCounts[m.key]}</span>
            </button>
          ))}
          {cls && (
            <span className="rv-left" title="按当前范围与细项，这一类还没裁的张数（含这一屏）">
              本类还剩 <b>{cls === '*' ? classTotal : (classCounts[cls] || 0)}</b>
              {cards.length ? `（本屏 ${cards.length}）` : ''}
            </span>
          )}
        </div>
      )}
      <details className="rv-detail">
        <summary className="muted">本类细项</summary>
        <div className="rv-toolbar">
          <label className="muted" title="一批载入多少张卡。缺省 30 = 一屏能裁完的量；改了点「重新载入」。">
            条数 <input value={limit} onChange={(e) => setLimit(+e.target.value || 30)} size={4} />
          </label>
          <label className="muted" title="默认只出全书从未裁过的字位（跨批次去重），所以「条数」数的是净新卡。勾上则把已裁过的也一并载入——复核自己裁过的、或想改主意时用（此时提交后不自动翻下一批）。">
            <input type="checkbox" checked={inclDecided} onChange={(e) => setInclDecided(e.target.checked)} /> 含已裁决
          </label>
          <label className="muted" title="顺序闸：字位旁边那条切分线有多种切法且还没 review 时，这个字位先不出卡。取消勾选可整批看全部。">
            <input type="checkbox" checked={gate} onChange={(e) => setGate(e.target.checked)} /> 先切线后字符
          </label>
          <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册页自动命名" /></label>
        </div>
      </details>
      {cls === 'replace_align' && subCounts && (
        <div className="rv-classes" data-testid="rv-subs">
          <span className="muted">本类细项</span>
          {subMeta.map((m) => (
            <button key={m.key} data-sub={m.key} className={raSub === m.key ? 'on' : ''}
                    onClick={() => pickSub(m.key as 'grid' | 'tail' | 'manual')} title={m.hint}>
              {m.label}<span className="n">{subCounts[m.key] || 0}</span>
            </button>
          ))}
          {raSub === 'grid' && (
            <>
              <label className="muted" title="网格一屏几张（40–60 为宜）；改了点「重新载入」">
                一屏 <input value={gridN} onChange={(e) => setGridN(+e.target.value || 60)} size={3} />
              </label>
              <label className="muted" data-testid="ra-shadow-toggle"
                     title={shadowAvail ? `影子把握 ≥0.9 且影子字 == 整理本字的卡排最前、标「影子预勾」；仍要点提交，不会自动放行`
                                        : '没有影子预测文件（<ws>/cache/shadow/<书>.json），此项不可用'}>
                <input type="checkbox" checked={shadowAvail && useShadow} disabled={!shadowAvail}
                       onChange={(e) => { setUseShadow(e.target.checked); load(true, 'replace_align', 'grid', e.target.checked) }} />
                {' '}使用影子预勾{shadowAvail ? `（本屏 ${countShadowPre(gridCards)} 张）` : ''}
              </label>
              <button className="rv-occl-all" data-testid="ra-submit" onClick={submitGrid}
                      disabled={groupBusy || !gridCards.length}
                      title="一次写完整屏：没点的采信（写 confirm，字 = 整理本字）；点了「要细审」的转到逐张，不写裁决">
                提交这一屏 {gridCards.length} 张（采信 {gridCards.filter((c) => (gridStates[c.id] ?? 'accept') === 'accept').length} · 要细审 {gridCards.filter((c) => gridStates[c.id] === 'review').length}）
              </button>
            </>
          )}
        </div>
      )}
      {cls === 'occluded' && (classCounts?.occluded || 0) > 0 && (
        <div className="rv-classes">
          <button className="rv-occl-all" onClick={confirmOccludedGroup} disabled={groupBusy}
                  title="印章遮挡卡默认填整理本字（整理本此位空的判非字），字形不入库；一键把这一组全部按默认提交">
            印章遮挡 · 整组确认 {classCounts?.occluded} 格
          </button>
        </div>
      )}
      {gateNote && (
        <div className="muted rv-gate-note" style={{ color: 'var(--ochre)' }}>
          ⊘ {gateNote.n} 位被顺序闸挡下——它们的格线有<b>多种切法</b>还没 review。
        </div>
      )}
      <div className="rv-help">
        <span dangerouslySetInnerHTML={{ __html: '键盘：' + (CLASS_HELP[classHelpKey(cls, raSub)] ?? DEFAULT_HELP) }} />{' '}
        <label className="muted" title="上下文缺省显示整理本对位原文（对不上的格退回刻本定字、字色浅一档）；勾上改看刻本这边的读法（定字 → 库 → OCR）">
          <input type="checkbox" checked={ctxKeben} onChange={(e) => setCtxKeben(e.target.checked)} /> 上下文用刻本读法
        </label>
      </div>
      {cls === 'replace_align' && raSub === 'grid' && gridCards.length > 0 && (
        <ReplaceAlignGrid cards={gridCards} states={gridStates} onToggle={toggleGrid} />
      )}
      <div className="rvgrid">
        {cards.map((c, i) => {
          if (isHidden(c)) return null
          return (
            <ReviewCardView
              key={c.id} idx={i} c={c} book={book} isCurrent={i === cur}
              verdict={verdicts.current[c.id]}
              keys={keyList(c, rare.current[c.id])}
              ctxImgOpen={!!ctxImgOpen.current[i]}
              aroundCtx={around.current[aroundKey(c)]}
              rareOut={rareOut.current[i]}
              onFocus={() => focus(i)}
              onSet={(shape: string, done?: string) => setVerdict(i, shape, done)}
              onSetNoGlyphLib={(checked: boolean) => setNoGlyphLib(i, checked)}
              onSetGuess={(g: string) => setGuess(i, g)}
              onSetApprox={(patch) => setApprox(i, patch)}
              onToggleCtxImg={() => toggleCtxImg(i)}
              onFetchRare={(force?: boolean) => fetchRareFor(i, force)}
              contextImgSrc={contextImgUrl(book, c.page, c.col, c.slot)}
              cls={c.cls}
              jysOpen={!!jysOpen.current[c.id]}
              onJysNone={() => { jysOpen.current[c.id] = true; bump() }}
              ctxKeben={ctxKeben}
            />
          )
        })}
      </div>
    </div>
  )
}
