import { useState } from 'react'
import { withWorkspace } from '../../api/client'
import { postEvents } from '../../api/events'
import { fetchSlotCountCards, fetchSlotCountVerdicts } from '../../api/slotCount'
import type { SlotCountCard } from '../../api/slotCount'
import { usePersistedPages } from '../../hooks/usePersistedPages'
import './slotCount.css'

// Step3 逐列字数人裁（2026-09-18）。为什么要有这个见
// `review/slot_count_cards.py` 模块头：`chars_per_line` 是页级版式常量，
// 少数列真的比常量多/少刻了一个字时 DP 会把多出的字压进某一格（bxgb p33c19
// 实测 slot21 压了三个字）——格高/period 比值判不出这种挤压（两个方向都测过
// 假阳性/假阴性），目前没有可靠的自动信号，只能人逐列数。
//
// 跟 HeadRaisePanel 的差别：那边答案是小枚举（抬几格，1~3 顶天），按钮排得开；
// 这里答案是开区间整数（可能是 19、20、21、22、23……），用数字输入框 +
// 「就是常量」快捷键，不做成按钮墙。

const STEP = 'row_segment'
const DEFAULT_CHARS_PER_LINE = 21   // 没读到 book 元信息时的兜底展示值，不影响提交

export function SlotCountPanel({ book, pages: pagesProp }: { book: string; pages?: string }) {
  // `pages` 由页面（StepLayout 的板块①）传下来时以它为准；不传则退回
  // 面板自己记的那份。此前只有后者，于是 Step3 的切线台与 Step7 的阻塞
  // 切线台圈的是不同批页，看起来「两个台不重合」——而机制上
  // blocking ⊆ all 恒成立（计划书 §1.2 实测）。
  const [ownPages, setOwnPages] = usePersistedPages('slotcount', book, 'dev_set')
  const pages = pagesProp ?? ownPages
  const setPages = pagesProp === undefined ? setOwnPages : () => {}
  const [batchInput, setBatchInput] = useState('')
  const [onlyTodo, setOnlyTodo] = useState(true)
  const [cards, setCards] = useState<SlotCountCard[]>([])
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [done, setDone] = useState<Record<string, number>>({})
  // 这一列字距是否均匀（缺省 true）。标 false 的列 Step3 会放宽等距先验。
  const [uniform, setUniform] = useState<Record<string, boolean>>({})
  const [msg, setMsg] = useState('')

  const batch = () => batchInput.trim() || `${book}-slotcount-review`

  async function load() {
    setMsg('载入中…')
    const b = batch()
    let d
    try {
      d = await fetchSlotCountCards(book, pages || 'dev_set')
    } catch (e) {
      setMsg('失败：' + (e as Error).message)
      return
    }
    let verdicts: Record<string, { n_slots: number; uniform?: boolean }> = {}
    try {
      verdicts = (await fetchSlotCountVerdicts(b)).verdicts || {}
    } catch {
      // 新批次，没有裁决可读
    }
    const dn: Record<string, number> = {}
    const dr: Record<string, string> = {}
    const du: Record<string, boolean> = {}
    for (const c of d.cards) {
      const v = verdicts[c.id]
      if (v) {
        dn[c.id] = v.n_slots
        dr[c.id] = String(v.n_slots)
        // 缺省均匀：老裁决没这个键，不能因为加了新键就改掉它们的含义
        du[c.id] = v.uniform !== false
      }
    }
    setDone(dn)
    setDraft(dr)
    setUniform(du)
    setCards(d.cards)
    setMsg(`${d.n} 张卡 → 批次 ${b}`)
  }

  async function submit(c: SlotCountCard, n: number) {
    // `uniform` 缺省 true（等距是版式常识）。标 false 的列，Step3 会把等距
    // 先验降下来——见 row_boundaries.NONUNIFORM_LAM。
    const uni = uniform[c.id] !== false
    try {
      await postEvents({
        batch: batch(), step: STEP, unit: 'column', kind: 'n_body_slots',
        events: [{ id: c.id, n_slots: n, uniform: uni, t: Date.now() }],
      })
      setDone((p) => ({ ...p, [c.id]: n }))
      setMsg(`已裁 ${Object.keys(done).length + 1} / ${cards.length} → 批次 ${batch()}`)
    } catch (e) {
      setMsg('写入失败：' + (e as Error).message)
    }
  }

  function onInput(c: SlotCountCard, v: string) {
    setDraft((p) => ({ ...p, [c.id]: v }))
  }

  function onConfirm(c: SlotCountCard) {
    const v = draft[c.id]
    const n = parseInt(v, 10)
    if (!Number.isFinite(n) || n <= 0) {
      setMsg('请输入一个正整数')
      return
    }
    void submit(c, n)
  }

  const visible = cards.filter((c) => (onlyTodo ? done[c.id] == null : true))

  return (
    <div className="card">
      <h2>Step3 逐列字数核对 <span className="muted">一列一张，数实际字数，跟常量不同就填</span></h2>
      <p className="muted sc-howto">
        每张卡是<b>一整列</b>，红线是当前 Step3 切出的格线——<b>逐格数字数</b>，
        跟版式常量（通常 {DEFAULT_CHARS_PER_LINE}）不同就在输入框填<b>实际字数</b>后回车/点确认。
        不含夹注小字、不含版心；数不清或没把握的留空跳过，别猜。
        填完这一页 Step3 会自动重切，下次刷新看新格线是否对上。
      </p>
      <div className="sc-toolbar">
        <label className="muted">页 <input value={pages} onChange={(e) => setPages(e.target.value)} size={10} /></label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册自动命名" /></label>
        <label className="muted"><input type="checkbox" checked={onlyTodo} onChange={(e) => setOnlyTodo(e.target.checked)} /> 只看未裁</label>
        <button onClick={load}>载入</button>
        <span className="muted">{msg}{cards.length ? `（已裁 ${Object.keys(done).length}）` : ''}</span>
      </div>
      <div className="scgrid">
        {visible.map((c) => {
          const isDone = done[c.id] != null
          const draftVal = draft[c.id] ?? ''
          const changed = isDone && draftVal !== '' && parseInt(draftVal, 10) !== done[c.id]
          return (
            <article key={c.id} className="sccard" data-v={isDone ? 'done' : ''}>
              <div className="sc-img-wrap">
                <img src={withWorkspace(c.img)} alt="" />
              </div>
              <div className="sc-body">
                <h3>
                  {c.book}/{c.page} <em>第 {c.col} 列</em>
                  <span className="sc-det muted">现有 {c.det_n_slots ?? '—'} 格{c.det_ok === false ? '（未过闸）' : ''}</span>
                </h3>
                <div className="sc-row">
                  <input
                    type="number" min={1} className="sc-input"
                    value={draftVal}
                    placeholder={String(c.det_n_slots ?? DEFAULT_CHARS_PER_LINE)}
                    onChange={(e) => onInput(c, e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') onConfirm(c) }}
                  />
                  <button onClick={() => onConfirm(c)}>{isDone ? '改' : '确认'}</button>
                </div>
                <label className="sc-uni muted" title="刻工前疏后密之类：字数对了但字距不等。勾上后 Step3 放宽等距先验，不再为了拉齐格高把大字劈成两格">
                  <input type="checkbox"
                         checked={uniform[c.id] === false}
                         onChange={(e) => setUniform((p) => ({ ...p, [c.id]: !e.target.checked }))} />
                  {' '}字距不均匀
                </label>
                {isDone && !changed && <b className="sc-ok">✓ 已存 {done[c.id]} 字</b>}
                {changed && <span className="sc-pending">未提交改动</span>}
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}
