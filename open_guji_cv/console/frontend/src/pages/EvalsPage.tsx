import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { RulersPanel } from '../components/evals/RulersPanel'
import { RoundPanel } from '../components/evals/RoundPanel'
import { QualityPanel } from '../components/evals/QualityPanel'
import { EvalsPanel } from '../components/evals/EvalsPanel'

// D6：跨步页面 /<book>/evals/。方案 §三：27 个评测器 + 判据看板（v1 health.js）
// + 四把尺子——本来就不按步分，硬塞进某个 Step 页面会产生错位。
// health.js 的三块（四把尺子/一轮体检/质量看板）+ evals.js（评测器列表）
// 原本挤在 v1 的 review tab 里，这里合成一个独立页面。
export function EvalsPage() {
  const { book = '' } = useParams()
  const [pages, setPages] = useState('dev_set')

  return (
    <div>
      <div className="card">
        <label className="muted">体检/质量看板用的页码 <input value={pages} onChange={(e) => setPages(e.target.value)} size={16} /></label>
      </div>
      <RulersPanel book={book} />
      <RoundPanel book={book} pages={pages} onFillPages={setPages} />
      <QualityPanel book={book} pages={pages} />
      <EvalsPanel />
    </div>
  )
}
