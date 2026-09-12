import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  cellShrinkPatchUrl, cellShrinkRandContextUrl, fetchCellShrinkRandSample,
} from '../api/cellShrinkRand'
import type { CellShrinkRandRow } from '../api/cellShrinkRand'
import { postEvents } from '../api/events'
import { fetchReviewVerdicts } from '../api/review'
import { consumedMsg } from '../domain'
import '../components/review/review.css'

// Step4 随机层裁决台（overview 2026-09-11 下发：01-补随机层金标.md）。
//
// Step4 现在报 R4 = 0.51%，但没有人工核校的独立基准说这个数对不对。
// `self_assess_r1~r4` 虽然也叫 stratum=rand，但 label_origin 全是 model——
// 算法标自己，循环论证，不能当验收基准。这里出的候选是从全书（现有产物
// 范围内）正文页字格里**等概率随机**抽的，不看任何旗标；卡片也不叠任何
// 算法判断（不显示 flags）——印上去人就会顺着点，测出来的是算法自己
// （head-raise-presence 那批的教训）。
//
// 裁决走既有的 POST /api/events（kind=confirm, payload.v=seg_defect,
// payload.quality=<clean|upstream_miscut|truncated|contaminated|not_text>），落
// char-segmentation/instances，stratum=rand_human 与既有的 self_assess
// 系列和其余定向层分开，报数时不能合并算。
//
// `upstream_miscut`（用户 2026-09-12 加）：格子本身从 Step3 行切分就切错了
// 位置/范围（不是「Step4 收缩没收干净」那种量级的问题）——混进来的是实质性
// 的另一部分内容（如相邻字的一大截笔画），Step4 收缩无论怎么调都救不回来，
// 这一步测不出、也修不了，得反馈给 Step3。与 `contaminated`（收缩阶段留了
// 一点残留：界行线/版框条/邻字一点点残墨）分开统计，别把上游的锅记在
// Step4 头上。

type Verdict = 'clean' | 'upstream_miscut' | 'truncated' | 'contaminated' | 'not_text'
const VERDICT_ORDER: Verdict[] = ['clean', 'upstream_miscut', 'truncated', 'contaminated', 'not_text']
const VERDICT_LABEL: Record<Verdict, string> = {
  clean: 'clean · 框准字全',
  upstream_miscut: 'upstream_miscut · 上游切分错了',
  truncated: 'truncated · 字被切掉',
  contaminated: 'contaminated · 混进杂物',
  not_text: 'not_text · 不是一个字',
}
const VERDICT_KEY: Record<Verdict, string> = {
  clean: '1', upstream_miscut: '2', truncated: '3', contaminated: '4', not_text: '5',
}

function slotOf(id: string): number {
  const parts = id.split(':')
  const raw = parts[parts.length - 1]
  return parseInt(raw, 10)
}

export function Step4Page() {
  const { book = '' } = useParams()
  const [n, setN] = useState(400)
  const [rows, setRows] = useState<CellShrinkRandRow[]>([])
  const [nPool, setNPool] = useState(0)
  const [msg, setMsg] = useState('')
  const [todoOnly, setTodoOnly] = useState(false)
  const [cur, setCur] = useState(0)
  const [, forceRender] = useState(0)
  const bump = () => forceRender((x) => x + 1)

  const verdicts = useRef<Record<string, { v: Verdict; t: number }>>({})
  const batchId = `cell-shrink-rand-r1`

  async function load() {
    setMsg('载入中…')
    const d = await fetchCellShrinkRandSample(n, 20260911, 'r1')
    setNPool(d.n_pool)
    try {
      const done = (await fetchReviewVerdicts(batchId)).verdicts || {}
      for (const [id, v] of Object.entries(done)) {
        if (v.done) verdicts.current[id] = { v: v.done as Verdict, t: v.ts || 0 }
      }
    } catch {
      // 批次还不存在就是没裁过
    }
    setRows(d.rows)
    setCur(0)
    tally(d.rows, d.n_pool)
  }

  function tally(list: CellShrinkRandRow[], pool?: number) {
    const done = list.filter((r) => verdicts.current[r.id]).length
    setMsg(`候选池 ${pool ?? nPool ?? '—'} 格 · 抽出 ${list.length} 张 · 已裁 ${done}`)
  }

  useEffect(() => {
    setRows([])
    verdicts.current = {}
    if (!book) return
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book])

  function setVerdict(id: string, v: Verdict) {
    const prev = verdicts.current[id]
    if (prev && prev.v === v) {
      delete verdicts.current[id]
    } else {
      verdicts.current[id] = { v, t: Date.now() }
    }
    bump()
    tally(rows)
  }

  async function submit() {
    const items = Object.entries(verdicts.current)
    if (!items.length) { setMsg('还没有裁决'); return }
    setMsg('提交中…')
    const events = items.map(([id, v]) => ({
      id, v: 'seg_defect', quality: v.v, stratum: 'rand_human', t: v.t,
    }))
    try {
      const r = await postEvents({ batch: batchId, step: 'cell_shrink', unit: 'cell', kind: 'confirm', events })
      setMsg(`已写入 ${r.appended ?? events.length} 条事件 → 批次 ${batchId}` + consumedMsg(r))
    } catch (e) {
      setMsg('提交失败：' + (e as Error).message)
    }
  }

  const visible = rows.filter((r) => !todoOnly || !verdicts.current[r.id])

  function focus(i: number) {
    if (!visible.length) return
    const j = Math.max(0, Math.min(i, visible.length - 1))
    setCur(j)
    document.getElementById(`s4c${j}`)?.scrollIntoView({ block: 'nearest' })
  }

  function setVerdictAt(i: number, v: Verdict) {
    const r = visible[i]
    if (!r) return
    setVerdict(r.id, v)
  }

  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      const target = ev.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      if (!visible.length) return
      if (ev.key === 'ArrowRight' || ev.key === 'j') { focus(cur + 1); ev.preventDefault() }
      else if (ev.key === 'ArrowLeft' || ev.key === 'k') { focus(cur - 1); ev.preventDefault() }
      else if (['1', '2', '3', '4', '5'].includes(ev.key)) {
        const v = VERDICT_ORDER[+ev.key - 1]
        setVerdictAt(cur, v)
        // 「只看未裁」时裁完这张卡会从列表里消失，同一个 cur 索引指向的
        // 已经是收缩后列表的下一张——再 focus(cur+1) 就会跳过一张，
        // 焦点看着像瞎跳。这个筛选模式下干脆不自动前进，原地停留。
        if (!todoOnly) focus(cur + 1)
        ev.preventDefault()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, cur, todoOnly])

  return (
    <div className="card">
      <h2>Step4 随机层裁决 <span className="muted">给字框收缩的缺陷率立一把真人核校过的尺子</span></h2>
      <div className="rv-toolbar">
        <label className="muted">抽样数
          <input type="number" value={n} onChange={(e) => setN(Number(e.target.value) || 400)} style={{ width: '5rem', marginLeft: '.3rem' }} />
        </label>
        <label className="muted"><input type="checkbox" checked={todoOnly} onChange={(e) => setTodoOnly(e.target.checked)} /> 只看未裁</label>
        <button onClick={load}>载入</button>
        <button onClick={submit}>提交裁决</button>
        <span className="muted">{msg}</span>
      </div>
      <div className="rv-help">
        左边是<b>语境图</b>（原图裁一块，<span style={{ color: '#c00' }}>红框</span>=Step4 紧裁框，
        <span style={{ color: '#0078f0' }}>蓝框</span>=Step3 切分原框），回答「这个框圈的是不是恰好
        一个整字」；右边是<b>成品图块</b>，回答「下游拿到的是什么」。这批候选是从全书正文页字格里
        等概率随机抽的（现有产物范围：vol01/vol02），不叠任何算法判断——判的时候只看图。
        键盘：<b>1</b> clean · <b>2</b> upstream_miscut · <b>3</b> truncated ·
        <b>4</b> contaminated · <b>5</b> not_text · <b>←/→</b>（或 <b>k/j</b>）翻卡。
        <b>upstream_miscut</b> 跟 <b>contaminated</b> 的区别：前者是 Step3 格子本身切错了位置/范围
        （混进来的是相邻字的一大截，Step4 收缩救不回来，得反馈给 Step3）；后者是 Step4 收缩
        留了一点残留（界行线/邻字一点残墨），是这一步自己的问题。
      </div>
      <div className="rvgrid">
        {visible.map((r, i) => {
          const v = verdicts.current[r.id]?.v
          return (
            <article
              key={r.id} id={`s4c${i}`} className={`rvcard${i === cur ? ' cur' : ''}`}
              data-done={v} onClick={() => focus(i)}
            >
              <div className="rvhead">
                <b>{r.id}</b>
              </div>
              <div className="rvbody">
                <div className="rvimgcol">
                  <img src={cellShrinkRandContextUrl(r.book, r.page, r.col, slotOf(r.id))} alt="语境图" loading="lazy" />
                  <span className="rvzi">语境图</span>
                </div>
                <div className="rvimgcol">
                  <img src={cellShrinkPatchUrl(r.book, r.patch_key)} alt="成品图块" loading="lazy" />
                  <span className="rvzi">成品图块</span>
                </div>
              </div>
              <div className="rvseg">
                {VERDICT_ORDER.map((k) => (
                  <button
                    key={k} className={v === k ? 'on' : ''}
                    onClick={(e) => { e.stopPropagation(); focus(i); setVerdict(r.id, k) }}
                  >
                    <kbd>{VERDICT_KEY[k]}</kbd> {VERDICT_LABEL[k]}
                  </button>
                ))}
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}
