import { useState } from 'react'
import { fetchReviewCards, fetchAroundBatch, contextImgUrl } from '../../api/review'
import { keyList } from './candidates'
import { ReviewCardView } from './ReviewCardView'
import type { AroundContext, ReviewCard } from '../../types/review'
import './review.css'

// 「按坐标查卡」（用户 2026-09-17）：人裁时报出一个字位（如 4:1:21），要立刻把
// 那张定字裁决卡片调出来对着看。原来只能先猜它在哪一页、把页范围调过去载入，
// 还可能因为**它已自动进库 / 已裁过 / 旁边切线没裁**而根本不出卡，对着空面板
// 分不清是"没问题"还是"被吞了"。
//
// 走后端 `pages=cells:<坐标>` 这条通路（`review/cards.py`），与点名清单 `list:`
// 同一个 `only_ids` 分支，因此**不受 only / 顺序闸 / 已裁去重约束**——点名要看的
// 就得出得来。
//
// 本面板**只看不裁**：裁决仍在下面的「定字裁决」里做。两处都能提交的话，
// 批次归属、touched 集合、已裁去重这三件事就要各维护一套，是白给的 bug 来源。
export function CellLookupPanel({ book }: { book: string }) {
  const [input, setInput] = useState('')
  const [cards, setCards] = useState<ReviewCard[]>([])
  const [around, setAround] = useState<Record<string, AroundContext>>({})
  const [msg, setMsg] = useState('')
  const [ctxOpen, setCtxOpen] = useState<Record<number, boolean>>({})

  async function look() {
    const q = input.trim()
    if (!q) return
    setMsg('查询中…')
    setCards([])
    try {
      // only/gate 传 all/false 只是为了语义清楚：cells: 分支在后端本就不看它们。
      const d = await fetchReviewCards(book, `cells:${q}`, 'all', false, 200, false)
      setCards(d.cards)
      if (!d.cards.length) {
        setMsg(`没找到 ${q}——检查页/列/格是否存在，或该页还没跑 seed_admit`)
        return
      }
      setMsg(`${d.cards.length} 张`)
      fetchAroundBatch(book, 10, 10, d.cards.map((c) => ({ page: c.page, col: c.col, slot: c.slot })))
        .then((r) => setAround(r.around || {}))
        .catch(() => {})
    } catch (e) {
      setMsg(`查询失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return (
    <div className="card">
      <label>
        <b>按坐标查卡</b>{' '}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') look() }}
          size={34}
          placeholder="4:1:21 或 4:1:21,6:8:1（页:列:格）"
          title="页:列:格，可带书号；多个用逗号分隔。不受顺序闸与「已裁决」过滤影响"
        />
      </label>
      <button onClick={look} style={{ marginLeft: '.5rem' }}>查看</button>
      <span className="muted" style={{ marginLeft: '.6rem' }}>{msg}</span>
      {cards.map((c, i) => (
        <ReviewCardView
          key={c.id}
          idx={i}
          c={c}
          book={book}
          isCurrent={false}
          verdict={undefined}
          keys={keyList(c, undefined)}
          ctxImgOpen={!!ctxOpen[i]}
          aroundCtx={around[`${c.page}:${c.col}:${c.slot}`]}
          rareOut={undefined}
          onFocus={() => {}}
          onSet={() => {}}
          onSetNoGlyphLib={() => {}}
          onToggleCtxImg={() => setCtxOpen((m) => ({ ...m, [i]: !m[i] }))}
          onFetchRare={() => {}}
          contextImgSrc={contextImgUrl(book, c.page, c.col, c.slot)}
        />
      ))}
    </div>
  )
}
