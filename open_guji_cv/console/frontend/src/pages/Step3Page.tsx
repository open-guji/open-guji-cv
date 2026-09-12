import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchRulers } from '../api/evals'
import { CutlinePanel } from '../components/cutline/CutlinePanel'
import { PageRangeSelector, loadSavedPageRange } from '../components/common/PageRangeSelector'
import { ProgressGatePanel } from '../components/common/ProgressGatePanel'
import type { CustomMetric } from '../components/common/ProgressGatePanel'
import { JiazhuPanel } from '../components/jiazhu/JiazhuPanel'
import { ProductViewer } from '../components/ProductViewer'
import { usePages } from '../hooks/usePages'
import type { RulerRow } from '../types/evals'

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
  const [pageSel, setPageSel] = useState(() => loadSavedPageRange(STEP_ID, book))
  const [loadedBook, setLoadedBook] = useState(book)
  if (book !== loadedBook) {
    setLoadedBook(book)
    setPageSel(loadSavedPageRange(STEP_ID, book))
  }
  const [rulers, setRulers] = useState<RulerRow[] | null>(null)

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
      <PageRangeSelector book={book} stepId={STEP_ID} value={pageSel} onChange={setPageSel} />
      <ProgressGatePanel
        book={book}
        title="Step3→4 交接闸（闸3）"
        gateId="row_segment_gate"
        pages={pageSel}
        customMetrics={customMetrics}
      />
      <CutlinePanel book={book} />
      <JiazhuPanel book={book} />
      <ProductViewer book={book} step="row_segment" pages={pages} />
    </div>
  )
}
