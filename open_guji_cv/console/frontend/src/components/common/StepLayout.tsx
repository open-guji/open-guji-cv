import { useState, type ReactNode } from 'react'
import { PageRangeSelector, type PageRangeTypeFilter } from './PageRangeSelector'
import './step-layout.css'

// 板块骨架（《计划书-控制台四板块统一》§1）。十个 Step 页面自上而下一律四块：
//
//   ① 页范围选择  → 对下面所有板块生效；取值可自定义；输入缓存
//   ② 总览        → 展示①范围内的各项数据
//   ③ 裁决台      → 可多个；多个时用 tab 分，不并排堆叠
//   ④ 产物台      → 这一步做了什么：叠图 + 数值产物
//
// 盘点现状时十个页面**没有一个四块齐全**：Step4/6/8 没有页范围也没有总览，
// Step7 自己复刻了一份页范围（含自己的 localStorage），总览有 5 处重复实现。
// 这个组件只固化「顺序与容器」，不替各页决定内容——板块二三四都收 ReactNode。
//
// **页范围是唯一源**：由本组件持有并回调给各板块，面板内不再各自 useState。
// 此前 8 个面板用 `usePersistedPages` 各存各的页范围，与页面顶部完全不联动
// ——Step3 的切线台和 Step7 的阻塞切线台因此圈的是不同批页，看起来「两个台
// 不重合」，实际上机制上 blocking ⊆ all 恒成立（计划书 §1.2 实测）。

export interface StepLayoutReviewTab {
  /** tab 标题；只有一个裁决台时不显示 tab 条 */
  label: string
  /** 页面内唯一，用作 React key 与 tab 状态 */
  id: string
  node: ReactNode
  /** 右上角小字：待裁条数之类 */
  badge?: string
}

export interface StepLayoutProps {
  book: string
  stepId: string
  pages: string
  onPagesChange: (v: string) => void
  typeFilter?: PageRangeTypeFilter
  /** 板块②：总览。不传则不渲染这一块 */
  overview?: ReactNode
  /** 板块③：裁决台。空数组 = 这一步没有裁决 */
  reviews?: StepLayoutReviewTab[]
  /** 板块④：产物台 */
  product?: ReactNode
  /** 页范围之下、总览之上的提示条（深链提示等） */
  banner?: ReactNode
}

export function StepLayout({ book, stepId, pages, onPagesChange, typeFilter,
                            overview, reviews = [], product, banner }: StepLayoutProps) {
  const tabs = reviews.filter(Boolean)
  const [cur, setCur] = useState(0)
  // tab 数量会随 caps 门控变化（换册时某些面板会消失），越界就落回第一个
  const idx = cur < tabs.length ? cur : 0
  const active = tabs[idx]

  return (
    <div className="steplayout">
      <PageRangeSelector book={book} stepId={stepId} value={pages}
                         onChange={onPagesChange} typeFilter={typeFilter} />
      {banner}
      {overview}
      {tabs.length > 0 && (
        <div className="card slreview">
          {tabs.length > 1 && (
            <div className="sltabs">
              {tabs.map((t, i) => (
                <button key={t.id} className={i === idx ? 'on' : ''} onClick={() => setCur(i)}>
                  {t.label}
                  {t.badge ? <span className="slbadge">{t.badge}</span> : null}
                </button>
              ))}
            </div>
          )}
          {/* 只渲染当前 tab：各裁决台进页就拉卡片，全部挂载会让一个页面同时
              发四五个批量请求（Step3 有四个裁决台） */}
          {active?.node}
        </div>
      )}
      {product}
    </div>
  )
}
