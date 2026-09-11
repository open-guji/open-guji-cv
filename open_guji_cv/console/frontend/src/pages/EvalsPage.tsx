import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ThroughputPanel } from '../components/evals/ThroughputPanel'
import { RulersPanel } from '../components/evals/RulersPanel'
import { RoundPanel } from '../components/evals/RoundPanel'
import { QualityPanel } from '../components/evals/QualityPanel'
import { EvalsPanel } from '../components/evals/EvalsPanel'

// D6 + 2026-09-11 重构：跨步页面 /<book>/evals/。原先四个面板（四把尺子/一轮
// 体检/质量看板/评测器列表）平铺堆叠，没有区分「切分线 Step1-4」与「识别定字
// 线 Step5-8」，也没有全局统计视角——overview 审阅指出用户想要的「每册每页
// 输入输出、通道占比、performance」压根没地方看。
//
// 重排原则：
//   1. 吞吐量（新，`eval/throughput.py`）放最上面当总览——它是唯一横跨全部
//      Step 的统计，先看全局再看分线。
//   2. 按「用户 2026-09-09 定」的两条线分组：切分线（四把尺子=Step1-4）
//      与识别定字线（判据A-F+质量看板=Step5-8），标题直接点出对应 Step。
//   3. 评测器列表（27 个脚本罗列，日常工作流用不上）折叠到页面最下面，
//      默认收起——它是调试工具箱，不是决策要看的东西。
//   4. 每步的详细数据总结（用户正在让各步自己写）以后往哪接：见本文件
//      末尾的「各步小结」占位区注释。
export function EvalsPage() {
  const { book = '' } = useParams()
  const [pages, setPages] = useState('dev_set')
  const [showEvals, setShowEvals] = useState(false)

  return (
    <div>
      <ThroughputPanel book={book} />

      <div className="card">
        <label className="muted">切分线体检用的页码 <input value={pages} onChange={(e) => setPages(e.target.value)} size={16} /></label>
      </div>

      <h3 className="section-head">切分线 · Step1-4</h3>
      <RulersPanel book={book} />

      {/* 各步小结占位：Step0-4 各自的详细数据总结做好后，接一个
          <StepSummaryPanel step="border_detect" .../> 之类的卡片挂在这里。
          现在还没有对应数据源，先留这句注释占位，不要新建空组件。 */}

      <h3 className="section-head">识别与定字线 · Step5-8</h3>
      <RoundPanel book={book} pages={pages} onFillPages={setPages} />
      <QualityPanel book={book} pages={pages} />

      {/* 同上，Step5-8 各步小结的接入点。 */}

      <div className="muted" style={{ cursor: 'pointer', margin: '.8rem 0 .4rem' }} onClick={() => setShowEvals((v) => !v)}>
        {showEvals ? '▾' : '▸'} 评测器列表（27 个脚本，调试用，默认收起）
      </div>
      {showEvals && <EvalsPanel />}
    </div>
  )
}
