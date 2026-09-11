import { Link } from 'react-router-dom'
import type { StatusResponse } from '../types/status'
import { findStepByBackendId } from '../steps'

const STATUS_MARK: Record<string, string> = {
  fresh: '✓', stale: '~', missing: '·', failed: '✗', blocked: '⊘',
}

// 对应 v1 static/js/panels/overview.js 的状态矩阵。D2 第一版：能看，格子链接到
// 对应 Step 页面（v1 是点开"产物"面板，v2 里产物已按方案 §三 并入各 Step 页面）。
export function StatusMatrix({ book, status }: { book: string; status: StatusResponse }) {
  const pageList = status.pages

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="matrix">
        <thead>
          <tr>
            <th className="step">步骤</th>
            <th>汇总</th>
            {pageList.map((p) => <th key={p}>{p}</th>)}
          </tr>
        </thead>
        <tbody>
          {Object.entries(status.steps).map(([sid, d]) => {
            const c = d.counts
            const stepMeta = findStepByBackendId(sid)
            const label = stepMeta ? (
              <Link to={`/${book}/step/${stepMeta.id}/`}>{sid}</Link>
            ) : sid
            return (
              <tr key={sid}>
                <th className="step">{label}</th>
                <td className="counts">
                  <span className="s-fresh">{c.fresh}</span>
                  <span className="s-stale">{c.stale}</span>
                  <span className="s-missing">{c.missing}</span>
                  <span className="s-failed">{c.failed}</span>
                  <span className="s-blocked">{c.blocked}</span>
                </td>
                {pageList.map((p) => {
                  const cell = d.pages[String(p)]
                  if (!cell) return <td key={p} className="cell s-missing">·</td>
                  const t = cell.error ? cell.error : (cell.elapsed != null ? `${cell.elapsed}s` : '')
                  return (
                    <td key={p} className={`cell s-${cell.status}`} title={`${cell.status}${t ? ' · ' + t : ''}`}>
                      {STATUS_MARK[cell.status] || '?'}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
