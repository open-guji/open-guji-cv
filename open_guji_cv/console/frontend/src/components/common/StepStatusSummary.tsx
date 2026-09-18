import { Link } from 'react-router-dom'
import { useWsPath } from '../../hooks/useWsPath'
import type { StepStatus } from '../../types/status'

// 产物新鲜度计数（✓新鲜 ~过期 ·缺失 ✗失败 ⊘阻塞）。同一段 markup 此前在
// Step0Page / Step5Page / StepPage 各写了一遍。
//
// ⚠️ 这**不是**板块②总览的替代品，两者数据源不同、答的问题也不同：
//   - 本组件：`/api/status` → 「这一步的产物跑了没、过期没」
//   - ProgressGatePanel：`/api/gate/{book}/summary` → 「这一步的闸判了什么」
// 盘点报告曾把它们一起算作「总览重复实现 5 处」，核实后只有
// `evals/GateSummaryPanel` 与 ProgressGatePanel 是真重复（同一接口），
// 而那个服务评测页、带闸切换 tab，合并反而削功能。这里只消掉形状重复。

export function StepStatusSummary({ book, status, label = '状态矩阵里这一步：' }: {
  book: string
  status: StepStatus | undefined
  label?: string
}) {
  const wsPath = useWsPath()
  if (!status) return null
  const c = status.counts
  return (
    <div className="muted step-status-summary">
      {label}
      <span className="counts">
        <span className="s-fresh">✓{c.fresh}</span>
        <span className="s-stale">~{c.stale}</span>
        <span className="s-missing">·{c.missing}</span>
        <span className="s-failed">✗{c.failed}</span>
        <span className="s-blocked">⊘{c.blocked}</span>
      </span>
      <Link to={wsPath(`/${book}/`)}>回总览看逐页详情</Link>
    </div>
  )
}
