import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchGateSummary } from '../api/evals'
import { BorderReviewPanel } from '../components/border-review/BorderReviewPanel'
import { PageLinePanel } from '../components/border-review/PageLinePanel'
import { PageRangeSelector, loadSavedPageRange } from '../components/common/PageRangeSelector'
import { ProgressGatePanel, foldPageRanges } from '../components/common/ProgressGatePanel'
import type { TypeBreakdownItem } from '../components/common/ProgressGatePanel'
import { ProductViewer } from '../components/ProductViewer'
import { usePages } from '../hooks/usePages'
import type { GateSummaryResponse } from '../types/evals'
import type { BorderReviewKind } from '../types/borderReview'

// Step1 边框与界行探测。裁决台（列探测/抬头/外框外延）用户 2026-09-11 定「以后
// 完全不走 artifact，都走控制台」后从 scripts/build_border_gold_reviews.py
// 迁入；同页也放 Step2 的 colborder 核校——它原属 build_column_border_review.py，
// 判的是「Step2 单列矫正削上下版框削得对不对」，但输入是 border_detect 的产物
// （page_column_windows），放这一页比另开 Step2 专页更贴近人裁的心智模型
// （见 overview 项目 02-控制台可视化.md 的现状查证）。
// 'pageline' 不在 BorderReviewKind 里——不是"点类别"那四张卡的形状
// （要拖坐标），用独立组件，这里只借 TABS 做页内切换。
type TabKey = BorderReviewKind | 'pageline'
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'cols', label: '列探测' },
  { key: 'head', label: '抬头有无' },
  { key: 'outer', label: '外框外延' },
  { key: 'colborder', label: 'Step2 上下版框核校' },
  { key: 'pageline', label: '下版框坐标金标' },
]

const STEP_ID = 'step1'

// 页面类型分类：2026-09-12 起闸1（border_detect_gate）接入
// clustering.page_type.classify_page_type，会给每页判 page_type/policy——
// 只是结构量粗判（skip: blank/cover/label；custom: edict；standard 类里
// body/roster/toc 还未细分，roster 的细化要靠切分产物，见 page_type.py
// refine_page_type，不在 Step1 能做到的范围内）。之前用闸1 L1（列数对不对）
// 权宜替代的做法（"疑似正文/疑似非正文"）已经被真判据取代。
type TypeFilterValue = 'all' | 'skip' | 'custom' | 'standard'
const TYPE_FILTER_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'standard', label: '正文类（standard）' },
  { value: 'custom', label: '窄列类（custom，如上諭）' },
  { value: 'skip', label: '非正文（skip：封面/书签/空白/牌记）' },
]

export function Step1Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)
  const [tab, setTab] = useState<TabKey>('cols')
  const [pageSel, setPageSel] = useState(() => loadSavedPageRange(STEP_ID, book))
  const [loadedBook, setLoadedBook] = useState(book)
  if (book !== loadedBook) {
    setLoadedBook(book)
    setPageSel(loadSavedPageRange(STEP_ID, book))
  }
  const [typeFilter, setTypeFilter] = useState<TypeFilterValue>('all')
  const [gateSummary, setGateSummary] = useState<GateSummaryResponse | null>(null)

  useEffect(() => {
    if (!book) { setGateSummary(null); return }
    fetchGateSummary(book, 'border_detect_gate', pageSel).then(setGateSummary).catch(() => setGateSummary(null))
  }, [book, pageSel])

  const skipPages = gateSummary
    ? gateSummary.pages.filter((p) => p.page_type_policy === 'skip').map((p) => p.page)
    : []
  const customPages = gateSummary
    ? gateSummary.pages.filter((p) => p.page_type_policy === 'custom').map((p) => p.page)
    : []
  const standardPages = gateSummary
    ? gateSummary.pages.filter((p) => p.page_type_policy === 'standard').map((p) => p.page)
    : []

  const typeBreakdown: TypeBreakdownItem[] = gateSummary
    ? [
        { label: '正文类（standard）', count: standardPages.length, ranges: foldPageRanges(standardPages) },
        { label: '窄列类（custom）', count: customPages.length, ranges: foldPageRanges(customPages) },
        { label: '非正文（skip）', count: skipPages.length, ranges: foldPageRanges(skipPages) },
        { label: '无产物', count: gateSummary.pages.filter((p) => p.status === 'missing').length },
      ]
    : []

  // typeFilter 只影响板块④产物查看的页码列表——板块③裁决台（BorderReviewPanel）
  // 保留自己的页范围输入，不吃这个筛选（03-Step页面统一设计.md §2.4：待裁决区
  // 刻意不抽象成统一联动，各面板形态差异大，硬联动只会两头不讨好）。
  const filteredPages = typeFilter === 'skip' ? skipPages
    : typeFilter === 'custom' ? customPages
    : typeFilter === 'standard' ? standardPages
    : pages

  return (
    <div>
      <PageRangeSelector
        book={book}
        stepId={STEP_ID}
        value={pageSel}
        onChange={setPageSel}
        typeFilter={{ options: TYPE_FILTER_OPTIONS, value: typeFilter, onChange: (v) => setTypeFilter(v as TypeFilterValue) }}
      />
      <ProgressGatePanel
        book={book}
        title="Step1→2 交接闸（闸1）"
        gateId="border_detect_gate"
        pages={pageSel}
        typeBreakdown={typeBreakdown}
      />
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
      {tab === 'pageline' ? <PageLinePanel book={book} /> : <BorderReviewPanel book={book} kind={tab} />}
      <ProductViewer
        book={book}
        step="border_detect"
        pages={filteredPages}
        pageTypeOf={(p) => gateSummary?.pages.find((r) => r.page === p)?.page_type ?? undefined}
      />
    </div>
  )
}
