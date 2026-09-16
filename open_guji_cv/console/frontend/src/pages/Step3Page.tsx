import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchRulers } from '../api/evals'
import { CutlinePanel } from '../components/cutline/CutlinePanel'
import { HeadRaiseCard } from '../components/border-review/HeadRaiseCard'
import { PageRangeSelector, loadSavedPageRange } from '../components/common/PageRangeSelector'
import { ProgressGatePanel } from '../components/common/ProgressGatePanel'
import type { CustomMetric } from '../components/common/ProgressGatePanel'
import { JiazhuPanel } from '../components/jiazhu/JiazhuPanel'
import { ProductViewer } from '../components/ProductViewer'
import { useDeepLink } from '../hooks/useDeepLink'
import { usePages } from '../hooks/usePages'
import type { RulerRow } from '../types/evals'
import { fetchStatus } from '../api/status'
import { backendIdFor, findStep } from '../steps'
import { useBookCaps } from '../hooks/useBookCaps'
import type { TypeBreakdownItem } from '../components/common/ProgressGatePanel'

// D3：Step3 逐字切分。切线（v1 cutline tab）与夹注（v1 jiazhu tab）按方案 §三
// 都归 Step3——都是 row_segment 的一部分（jiazhu_split 是 Step3 的子模块，
// 折线缝 utils/seam.py 同样服务 row_segment）。
//
// 板块②（overview 任务书-页面结构统一.md）：核实后闸3（row_segment_gate）
// 其实已经实现并登记在 GATE_IDS 里（README"未收"是滞后信息，跟 Step1 闸1
// 当初的情况一样）——L1（DP 无解/格数偏离）+ L2（R2/R2s flag）直接走
// gateId 现成路径。R1-R3 这几把"现值"尺子（eval/rulers.py::measure）不在
// GateSummaryResponse 形状里，另外接 customMetrics，与 gateId 同时传
// （ProgressGatePanel 本就支持两者并存）。
const STEP_ID = 'step3'

export function Step3Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)
  const deep = useDeepLink()
  // 深链（对勘报告的 missing/extra/列结构条目）带页号就用它当初始页范围
  const [pageSel, setPageSel] = useState(() =>
    deep.active ? String(deep.page) : loadSavedPageRange(STEP_ID, book))
  const [loadedBook, setLoadedBook] = useState(book)
  if (book !== loadedBook) {
    setLoadedBook(book)
    setPageSel(loadSavedPageRange(STEP_ID, book))
  }
  const [rulers, setRulers] = useState<RulerRow[] | null>(null)
  const { meta: bookMeta, caps } = useBookCaps(book)
  // 现代印刷链（modern_body）这一步叫 row_segment_runs，而且**没有闸3**
  // ——它是墨段 DP 切分，不走刻本那套格数判据。写死 row_segment_gate 会让
  // 整块总览显示「无产物 80」，写死 row_segment 会让产物查看全空（2026-09-15）。
  const step3Id = backendIdFor(findStep('step3'), bookMeta?.edition) ?? 'row_segment'

  const [modernCounts, setModernCounts] = useState<TypeBreakdownItem[]>([])

  // 现代链这一步没有闸，总览就没有「过闸/被拦」可报。改报逐页产物状态
  // （状态矩阵里现成的 fresh/stale/missing），至少让人看得出跑到哪了，
  // 而不是一张空卡片。
  useEffect(() => {
    if (!book || caps.hasStep3Gate) { setModernCounts([]); return }
    fetchStatus(book, bookMeta?.pipeline || 'modern_body', 'all')
      .then((st) => {
        const c = st.steps[step3Id]?.counts
        setModernCounts(c ? [
          { label: '产物最新（fresh）', count: c.fresh },
          { label: '产物过期（stale）', count: c.stale },
          { label: '无产物（missing）', count: c.missing },
          { label: '失败（failed）', count: c.failed },
        ] : [])
      })
      .catch(() => setModernCounts([]))
  }, [book, caps.hasStep3Gate, step3Id, bookMeta?.pipeline])

  useEffect(() => {
    if (!book) { setRulers(null); return }
    fetchRulers(book, pageSel || 'dev_set').then((r) => setRulers(r.rulers)).catch(() => setRulers(null))
  }, [book, pageSel])

  const customMetrics: CustomMetric[] = (rulers || [])
    .filter((r) => ['R1', 'R2', 'R2s', 'R2x', 'R3'].includes(r.key))
    .map((r) => {
      const v = r.value == null ? '—' : r.value.toFixed(2) + r.unit
      const good = r.goal === '0' ? r.num === 0 : (r.goal === '100%' ? r.num === r.den : null)
      return { label: `${r.key} ${r.title}`, value: v, tone: good === null ? undefined : (good ? 'ok' : 'bad') }
    })

  return (
    <div>
      {deep.active && (
        <div className="card" style={{ borderLeft: '3px solid #7a5c2e' }}>
          从对勘报告跳转而来：<b>p{deep.page}</b>
          {deep.col !== null && <> · 第 {deep.col} 列</>}
          <span className="muted" style={{ marginLeft: '.6rem' }}>
            整理本在这一列比我们多字（漏切）——在下面「切线」里看这一列的切分
          </span>
        </div>
      )}
      <PageRangeSelector book={book} stepId={STEP_ID} value={pageSel} onChange={setPageSel} />
      <ProgressGatePanel
        book={book}
        title="总览"
        gateId={caps.hasStep3Gate ? 'row_segment_gate' : undefined}
        pages={pageSel}
        customMetrics={caps.hasStep3Gate ? customMetrics : []}
        typeBreakdown={caps.hasStep3Gate ? undefined : modernCounts}
      />
      {/* 三块各按各的能力判，不再一刀切按版式名（见 src/capabilities.ts）：
          拖切线量的是「格线穿字」——只有固定格数的格位切分才有这回事；
          抬头是刻本的版式特征；夹注指双行小注切分。三个接口在现代排印本上
          实测都回 0 条。 */}
      {caps.hasGridCells && <CutlinePanel book={book} />}
      {caps.hasHeadRaise && <HeadRaiseCard book={book} />}
      {caps.hasJiazhu && <JiazhuPanel book={book} />}
      <ProductViewer book={book} step={step3Id} pages={pages} />
    </div>
  )
}
