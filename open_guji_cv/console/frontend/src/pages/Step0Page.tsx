import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { listBooks } from '../api/registry'
import { fetchStatus } from '../api/status'
import { ProductViewer } from '../components/ProductViewer'
import type { Book } from '../types/registry'
import type { StatusResponse } from '../types/status'

// 用户 2026-09-11 测试反馈 §2：Step0 预清理要把 books/<book>.yaml 里 preclean
// 段的规则原样显示出来（vol02 有真实配置：151/152 两页的反色带修复）。
// 只对手工登记过的页生效，不改磁盘原图，见 open-guji-cv utils/preclean.py。
export function Step0Page() {
  const { book = '' } = useParams()
  const [b, setB] = useState<Book | null>(null)
  const [status, setStatus] = useState<StatusResponse | null>(null)

  useEffect(() => {
    setB(null)
    setStatus(null)
    if (!book) return
    listBooks().then((bs) => setB(bs.find((x) => x.id === book) || null)).catch(() => {})
    fetchStatus(book, 'keben_body_v2').then(setStatus).catch(() => {})
  }, [book])

  const stepStatus = status?.steps['preclean']
  const precleanPages = b ? Object.keys(b.preclean).map(Number).sort((x, y) => x - y) : []
  // all_pages 未设 GUJI_WORKSPACE 时可能是空数组（不是 null/undefined），
  // `??` 兜底不到——用长度判断，退回 pages（dev_set 那份至少非空）。
  const allPages = (status?.all_pages?.length ? status.all_pages : status?.pages ?? []).map(Number)

  return (
    <div>
      <div className="card">
        <h2>Step0 预清理 <span className="muted">修反色带等扫描缺陷，原图永不改写</span></h2>
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
        {b && precleanPages.length === 0 && <p className="muted">这本书没有登记 preclean 规则（本来就不用修）。</p>}
        {precleanPages.map((p) => (
          <div key={p} className="card preclean-page">
            <h3 className="mono">第 {p} 页</h3>
            {b!.preclean[String(p)].map((rule, i) => (
              <div key={i} className="preclean-rule">
                <div className="mono preclean-kind">{rule.kind}</div>
                <pre className="json">{JSON.stringify(rule, null, 1)}</pre>
              </div>
            ))}
          </div>
        ))}
      </div>
      <ProductViewer book={book} step="preclean" pages={allPages} />
    </div>
  )
}
