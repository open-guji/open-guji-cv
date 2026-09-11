import { Link, useParams } from 'react-router-dom'
import { STEP5_SUBS } from '../steps'
import { RarePanel } from '../components/rare/RarePanel'

// Step5 分四小步，路由 /<book>/step/step5/<sub>/，见方案 §二。
// D7：生僻字候选（rare.py，原本嵌在定字卡片里）独立成 5-b 的可视化。
// 其余三路（5-a/5-c/5-d）现在控制台也没有独立面板，仍是骨架（D8 范围）。
export function Step5Page() {
  const { book = '', sub } = useParams()
  const meta = sub ? STEP5_SUBS.find((s) => s.id === sub) : undefined

  if (!sub) {
    return (
      <div className="card">
        <h2>Step5 字符识别</h2>
        <p className="muted">四路并行，互不投票（流程与模块.md §4）：</p>
        <ul>
          {STEP5_SUBS.map((s) => (
            <li key={s.id}><Link to={`/${book}/step/step5/${s.id}/`}>{s.title}</Link></li>
          ))}
        </ul>
      </div>
    )
  }

  if (sub === 'rare') {
    return <RarePanel book={book} />
  }

  return (
    <div className="card">
      <h2>{meta?.title ?? sub}</h2>
      <p className="muted">{book} · 这一路的可视化还没有搬进来（v2 骨架阶段）。</p>
    </div>
  )
}
