import { useRef, useState } from 'react'
import { fetchBorderReviewCards, fetchBorderReviewVerdicts } from '../../api/borderReview'
import { postEvents } from '../../api/events'
import { BORDER_REVIEW_SPECS } from '../../types/borderReview'
import type { BorderReviewCard, BorderReviewKind } from '../../types/borderReview'
import './borderReview.css'

// 用户 2026-09-11 定：「以后完全不走 artifact，都走控制台」。这四类裁决原先由
// scripts/build_border_gold_reviews.py（cols/head/outer）与
// scripts/build_column_border_review.py（colborder）生成一次性 Artifact 网页，
// 标完靠脚本导出金标。四类形状相同（一图 + N 档按钮，不带坐标拖拽），
// 一个组件按 kind 切规格（BORDER_REVIEW_SPECS）复用，不必四个面板各写一遍。
// 步骤（step）与事件 kind 的映射见 review/border_cards.py 顶部说明。

const STEP_OF: Record<BorderReviewKind, string> = {
  cols: 'border_detect', head: 'border_detect', outer: 'border_detect', colborder: 'column_warp',
}

export function BorderReviewPanel({ book, kind }: { book: string; kind: BorderReviewKind }) {
  const spec = BORDER_REVIEW_SPECS[kind]
  const [pages, setPages] = useState('dev_set')
  const [batchInput, setBatchInput] = useState('')
  const [onlyTodo, setOnlyTodo] = useState(true)
  const [cards, setCards] = useState<BorderReviewCard[]>([])
  const [msg, setMsg] = useState('')
  const verdicts = useRef<Record<string, string>>({})
  const [, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const batch = () => batchInput.trim() || `${book}-${kind}-review`

  async function load() {
    setMsg('载入中…')
    const b = batch()
    let d
    try {
      d = await fetchBorderReviewCards(book, kind, pages || 'dev_set')
    } catch (e) {
      setMsg('失败：' + (e as Error).message)
      return
    }
    let done: Record<string, { verdict: string }> = {}
    try {
      done = (await fetchBorderReviewVerdicts(b)).verdicts || {}
    } catch {
      // 新批次，没有裁决可读
    }
    verdicts.current = Object.fromEntries(Object.entries(done).map(([k, v]) => [k, v.verdict]))
    setCards(d.cards)
    setMsg(`${d.n} 张卡 → 批次 ${b}`)
    bump()
  }

  async function decide(card: BorderReviewCard, v: string) {
    verdicts.current[card.id] = v
    bump()
    const payloadKey = spec.eventKind === 'border_class' ? 'border_class' : 'verdict'
    try {
      await postEvents({
        batch: batch(), step: STEP_OF[kind], unit: kind === 'colborder' ? 'column' : 'page',
        kind: spec.eventKind, events: [{ id: card.id, [payloadKey]: v, t: Date.now() }],
      })
      const n = Object.keys(verdicts.current).length
      setMsg(`已裁 ${n} / ${cards.length} → 批次 ${batch()}`)
    } catch (e) {
      delete verdicts.current[card.id]
      bump()
      setMsg('写入失败：' + (e as Error).message)
    }
  }

  const visible = onlyTodo ? cards.filter((c) => !verdicts.current[c.id]) : cards

  return (
    <div className="card">
      <h2>{spec.title} <span className="muted">不再走 artifact，裁决直接落这里</span></h2>
      <p className="muted br-howto">{spec.howto}</p>
      <div className="br-toolbar">
        <label className="muted">页 <input value={pages} onChange={(e) => setPages(e.target.value)} size={10} /></label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册/类型自动命名" /></label>
        <label className="muted"><input type="checkbox" checked={onlyTodo} onChange={(e) => setOnlyTodo(e.target.checked)} /> 只看未裁</label>
        <button onClick={load}>载入</button>
        <span className="muted">{msg}</span>
      </div>
      <div className="brgrid">
        {visible.map((c) => {
          const v = verdicts.current[c.id]
          return (
            <article key={c.id} className="brcard" data-v={v || ''}>
              <h3>
                {c.book}/{c.page}
                {kind === 'outer' && <em>{c.side === 'top' ? '上框' : '下框'}</em>}
                {kind === 'colborder' && <em>第 {c.col} 列 · {c.end === 'top' ? '上端' : '下端（已翻转）'}</em>}
              </h3>
              <img src={c.img} alt="" loading="lazy" className={kind === 'colborder' ? 'br-img-pixelated' : ''} />
              <div className="br-verdicts">
                {spec.options.map((opt) => (
                  <button
                    key={opt.key}
                    aria-pressed={v === opt.key}
                    style={v === opt.key ? { background: opt.soft, borderColor: opt.color, color: opt.color } : undefined}
                    onClick={() => decide(c, opt.key)}
                  >
                    {opt.label}
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
