import { useEffect, useState } from 'react'
import { StepStatusSummary } from '../components/common/StepStatusSummary'
import { useParams } from 'react-router-dom'
import { fetchPrecleanReport, precleanAfterUrl, precleanBeforeUrl, precleanOverlayUrl } from '../api/products'
import { postEvents } from '../api/events'
import { fetchInvertCards, invertPreviewUrl } from '../api/invert'
import type { InvertCard } from '../api/invert'
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

// 反色带候选送审（2026-10-22，Sheldon 定「自动认＋送审，人点头才修」）。`invert_detect` 每页自动找疑似
// 反色带，粗外框与窄反色带分不干净，所以一页一张卡：原图与照建议修法修后的图并排，人点「是」才修。
// 「是」的页 Step0 之后读修好的图（各步跟着过期重算）；「否」的页不再出卡（勾「含已否」可改判）。
function InvertReviewPanel({ book }: { book: string }) {
  const [cards, setCards] = useState<InvertCard[] | null>(null)
  const [err, setErr] = useState('')
  const [decided, setDecided] = useState(false)
  const [busy, setBusy] = useState<string>('')

  useEffect(() => {
    setCards(null)
    setErr('')
    fetchInvertCards(book, decided).then((r) => setCards(r.cards)).catch((e) => setErr((e as Error).message))
  }, [book, decided])

  async function decide(c: InvertCard, verdict: 'yes' | 'no') {
    setBusy(c.id)
    try {
      await postEvents({
        batch: `${book}-invert_detect`, step: 'invert_detect', unit: 'page', kind: 'inverted_band',
        events: [{ id: c.id, verdict, rules: c.rules, question: c.question, t: Date.now() }],
      })
      setCards((cs) => (cs || []).map((x) => (x.id === c.id ? { ...x, verdict } : x)))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="card">
      <h2>
        反色带候选 <span className="muted">自动找到的疑似反色带，点「是」才修；粗外框请点「否」</span>
        <label className="muted" style={{ marginLeft: 12 }}>
          <input type="checkbox" checked={decided} onChange={(e) => setDecided(e.target.checked)} /> 含已否
        </label>
      </h2>
      {err && <p className="muted">{err}</p>}
      {!cards && !err && <p className="muted">加载中…</p>}
      {cards && cards.length === 0 && <p className="muted">没有待审的候选（没跑过 invert_detect 的页不会出卡）。</p>}
      {cards?.map((c) => (
        <div key={c.id} className="card preclean-page">
          <h3 className="mono">
            第 {c.page} 页
            {c.verdict && <span className={c.verdict === 'yes' ? 's-fresh' : 's-failed'}>
              {' '}已判：{c.verdict === 'yes' ? '是，修' : '否，不修'}</span>}
          </h3>
          <div className="muted mono">
            {c.bands.map((b, i) => <span key={i}>黑条 {b.bbox.join(',')}（白缝 {b.flipped_rules} 道）　</span>)}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 320px' }}><div className="muted">原图</div>
              <img src={invertPreviewUrl(book, c.page, 'before')} alt="原图" style={{ maxWidth: '100%' }} /></div>
            <div style={{ flex: '1 1 320px' }}><div className="muted">修后预览</div>
              <img src={invertPreviewUrl(book, c.page, 'after')} alt="修后预览" style={{ maxWidth: '100%' }} /></div>
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <button disabled={busy === c.id} onClick={() => decide(c, 'yes')}>是，反色带，照此修</button>
            <button disabled={busy === c.id} onClick={() => decide(c, 'no')}>否，不是（外框等）</button>
          </div>
        </div>
      ))}
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
        <StepStatusSummary book={book} status={stepStatus} />
        {b && precleanPages.length === 0 && <p className="muted">这本书没有登记 preclean 规则（本来就不用修）。</p>}
      </div>
      {book && <InvertReviewPanel book={book} />}
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
