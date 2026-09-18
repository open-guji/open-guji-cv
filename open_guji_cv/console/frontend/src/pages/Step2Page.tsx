import { useParams } from 'react-router-dom'
import { useState } from 'react'
import { ProductViewer } from '../components/ProductViewer'
import { ColumnReviewPanel } from '../components/column-review/ColumnReviewPanel'
import { loadSavedPageRange } from '../components/common/PageRangeSelector'
import { StepLayout } from '../components/common/StepLayout'
import { ProgressGatePanel } from '../components/common/ProgressGatePanel'
import { usePages } from '../hooks/usePages'
import { backendIdFor, findStep } from '../steps'
import { useBookCaps } from '../hooks/useBookCaps'

const STEP_ID = 'step2'

// Step2 单列射影 + 闸2 可视化（overview 2026-09-11 下发，正本
// 项目进展/图片初步数字化/进度/Step2-单列射影/03-控制台可视化.md；
// 2026-09-11 页面结构统一核对，见同目录 任务书-页面结构统一.md）。
//
// 板块①：PageRangeSelector 控制板块②③④（03-Step页面统一设计.md §三 落位表）。
// 板块②：闸2（column_gate）是唯一已实现的闸，直接接 ProgressGatePanel + gateId，
// 不再本地重写一份——原本这里有一份重复的 GateSummaryPanel，跟
// components/evals/GateSummaryPanel.tsx 撞名但服务不同页面，两者都打同一个
// 后端 `/api/gate/{book}/summary`，统一走 ProgressGatePanel 之后不必再维护第三份。
// 板块③（列级 mixed/clean 人裁）：现状是空白——裁决数据只是
// `gold/column-warp/samples/*.json` 里的本地文件，没有后端 API 也没有前端入口，
// 不是"页面结构没摆对位置"，是这个板块本身还没做，另开任务处理，不在本次范围内。
// 板块⑤（列级准入候选标注）：01 号任务未产出，本次不设计不存在的判据界面。
export function Step2Page() {
  const { book = '' } = useParams()
  const [pageSel, setPageSel] = useState(() => loadSavedPageRange(STEP_ID, book))
  const [loadedBook, setLoadedBook] = useState(book)
  if (book !== loadedBook) {
    setLoadedBook(book)
    setPageSel(loadSavedPageRange(STEP_ID, book))
  }
  const pages = usePages(book, pageSel)
  const { meta: bookMeta } = useBookCaps(book)
  const step2Id = backendIdFor(findStep('step2'), bookMeta?.edition) ?? 'column_warp'

  return (
    <StepLayout
      book={book} stepId={STEP_ID} pages={pageSel} onPagesChange={setPageSel}
      overview={<ProgressGatePanel book={book} title="总览" gateId="column_gate" pages={pageSel} />}
      reviews={[{ id: 'column', label: '列清理裁决',
                  node: <ColumnReviewPanel book={book} pages={pageSel} /> }]}
      // 产物台：列窗口产物分链（刻本 column_warp / 现代 column_crop）。这里
      // 曾经看的是 column_gate（闸的判定）而非列窗口本身；也不该并排摆两个
      // 产物台（2026-09-15 用户反馈「有两个重复的产物台」）——闸的判定在
      // 上面那张总览卡里已经有了，这里只留列窗口。
      product={<ProductViewer book={book} step={step2Id} pages={pages} />}
    />
  )
}
