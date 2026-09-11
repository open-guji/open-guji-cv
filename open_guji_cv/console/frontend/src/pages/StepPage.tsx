import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { findStep } from '../steps'
import { fetchStatus } from '../api/status'
import { ProductViewer } from '../components/ProductViewer'
import type { StatusResponse } from '../types/status'

// D8：Step0/1/2/4 现在控制台没有对应面板，先给页面骨架 + 链接到状态矩阵
// 对应格（方案 §五 D8）+ 产物查看（用户 2026-09-11 测试反馈 §3）。
// 不重新设计这几步的可视化——那是本轮范围外的事，这里只做到"看得到这一步
// 现在跑得怎么样、看得到产物、能跳回总览细看"。
export function StepPage() {
  const { book = '', step } = useParams()
  const meta = step ? findStep(step) : undefined
  const [status, setStatus] = useState<StatusResponse | null>(null)

  useEffect(() => {
    setStatus(null)
    if (!book) return
    fetchStatus(book, 'keben_body_v2').then(setStatus).catch(() => {})
  }, [book])

  const backendId = meta?.backendIds[0]
  const stepStatus = backendId && status ? status.steps[backendId] : undefined
  // all_pages 未设 GUJI_WORKSPACE 时可能是空数组（不是 null/undefined），
  // `??` 兜底不到——用长度判断，退回 pages（dev_set 那份至少非空）。
  const pages = (status?.all_pages?.length ? status.all_pages : status?.pages ?? []).map(Number)

  return (
    <div>
      <div className="card">
        <h2>{meta?.title ?? step}</h2>
        <p className="muted">
          {book} · 这一步的具体面板还没有搬进来（v2 骨架阶段）。
          {meta && meta.backendIds.length > 0 && <> 对应后端 Step：{meta.backendIds.join(', ')}。</>}
        </p>
        {stepStatus && (
          <div className="muted step-status-summary">
            状态矩阵里这一步：
            <span className="counts">
              <span className="s-fresh">✓{stepStatus.counts.fresh}</span>
              <span className="s-stale">~{stepStatus.counts.stale}</span>
              <span className="s-missing">·{stepStatus.counts.missing}</span>
              <span className="s-failed">✗{stepStatus.counts.failed}</span>
              <span className="s-blocked">⊘{stepStatus.counts.blocked}</span>
            </span>
            <Link to={`/${book}/`}>回总览看逐页详情</Link>
          </div>
        )}
      </div>
      {backendId && <ProductViewer book={book} step={backendId} pages={pages} />}
    </div>
  )
}
