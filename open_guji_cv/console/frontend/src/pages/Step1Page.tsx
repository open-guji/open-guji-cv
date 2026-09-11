import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { BorderReviewPanel } from '../components/border-review/BorderReviewPanel'
import { ProductViewer } from '../components/ProductViewer'
import { usePages } from '../hooks/usePages'
import type { BorderReviewKind } from '../types/borderReview'

// Step1 边框与界行探测。裁决台（列探测/抬头/外框外延）用户 2026-09-11 定「以后
// 完全不走 artifact，都走控制台」后从 scripts/build_border_gold_reviews.py
// 迁入；同页也放 Step2 的 colborder 核校——它原属 build_column_border_review.py，
// 判的是「Step2 单列矫正削上下版框削得对不对」，但输入是 border_detect 的产物
// （page_column_windows），放这一页比另开 Step2 专页更贴近人裁的心智模型
// （见 overview 项目 02-控制台可视化.md 的现状查证）。
const TABS: Array<{ key: BorderReviewKind; label: string }> = [
  { key: 'cols', label: '列探测' },
  { key: 'head', label: '抬头有无' },
  { key: 'outer', label: '外框外延' },
  { key: 'colborder', label: 'Step2 上下版框核校' },
]

export function Step1Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)
  const [tab, setTab] = useState<BorderReviewKind>('cols')

  return (
    <div>
      <div className="card">
        <h2>Step1 边框探测 <span className="muted">版框、界行、抬头框</span></h2>
        <div className="seg" style={{ display: 'inline-flex', gap: '.3rem' }}>
          {TABS.map((t) => (
            <button key={t.key} aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <BorderReviewPanel book={book} kind={tab} />
      <ProductViewer book={book} step="border_detect" pages={pages} />
    </div>
  )
}
