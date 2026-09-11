import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchPrecleanReport, precleanAfterUrl, precleanBeforeUrl, precleanOverlayUrl } from '../api/products'
import { listBooks } from '../api/registry'
import { fetchStatus } from '../api/status'
import type { PrecleanReport } from '../api/products'
import type { Book } from '../types/registry'
import type { StatusResponse } from '../types/status'

// Step0 控制台可视化（overview 2026-09-11 下发，正本
// 项目进展/图片初步数字化/进度/Step0-预清理/02-控制台可视化.md）。preclean 不是
// core/step.py 注册的 Step，没有数值产物可读，走的是 render/overlay.py 现算的
// 三个专用接口，不是通用 ProductViewer（那条路走 /api/products 会 404）。
function PrecleanPanel({ book, page }: { book: string; page: number }) {
  const [report, setReport] = useState<PrecleanReport | null>(null)
  const [err, setErr] = useState('')
  const [showAfter, setShowAfter] = useState(false)

  useEffect(() => {
    setReport(null)
    setErr('')
    fetchPrecleanReport(book, page).then(setReport).catch((e) => setErr((e as Error).message))
  }, [book, page])

  if (err) return <p className="muted">{err}</p>
  if (!report) return <p className="muted">加载中…</p>

  return (
    <div className="products">
      <div className="card">
        <h2>反色带边界 <span className="muted">红=上沿 蓝=下沿 青=探测行</span></h2>
        <img src={precleanOverlayUrl(book, page)} alt="preclean 边界叠图" />
      </div>
      <div className="card">
        <h2>
          {showAfter ? '修复后' : '修复前'}
          <button className="pv-toggle" onClick={() => setShowAfter((v) => !v)}>
            切换到{showAfter ? '修复前' : '修复后'}
          </button>
        </h2>
        {showAfter && !report.precleaned_exists
          ? <p className="muted">还没生成产物，先跑 `python -m open_guji_cv.cli_v2 preclean {book}`</p>
          : <img src={showAfter ? precleanAfterUrl(book, page) : precleanBeforeUrl(book, page)}
                 alt={showAfter ? '修复后' : '修复前'} />}
      </div>
      <div className="card">
        <h2>带内墨占比</h2>
        {report.rules.map((r, i) => (
          <div key={i} className="mono preclean-report-rule">
            {r.kind !== 'inverted_band'
              ? r.kind
              : (
                <>
                  修前 {r.ink_before} → 修后 <b className={r.passed ? 's-fresh' : 's-failed'}>{r.ink_after}</b>
                  {' '}（闸 ≤{r.gate}，正文本底中位 {r.body_median} / p95 {r.body_p95}）
                  {r.passed ? ' 过闸' : ' ✗ 未过闸'}
                </>
              )}
          </div>
        ))}
      </div>
    </div>
  )
}

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
      </div>
      {precleanPages.map((p) => (
        <div key={p} className="card preclean-page">
          <h3 className="mono">第 {p} 页</h3>
          {b!.preclean[String(p)].map((rule, i) => (
            <div key={i} className="preclean-rule">
              <div className="mono preclean-kind">{rule.kind}</div>
              <pre className="json">{JSON.stringify(rule, null, 1)}</pre>
            </div>
          ))}
          <PrecleanPanel book={book} page={p} />
        </div>
      ))}
    </div>
  )
}
