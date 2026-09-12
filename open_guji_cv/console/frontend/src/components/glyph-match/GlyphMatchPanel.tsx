import { useState } from 'react'
import { fetchGlyphMatch, glyphMatchExemplarUrl } from '../../api/glyphMatch'
import type { GlyphMatchResult } from '../../api/glyphMatch'
import './glyphMatch.css'

// Step5-a 字形库匹配调试视图（overview 2026-09-11 方案：
// 08-5a方案-字形库匹配调试视图.md）。形态照抄 5-b RarePanel 的
// 页/列/格位查询交互，但数据源、候选修饰、图片展示都不同——见方案 §二
// 对照表。核心用途是肉眼比对"这是谁 vs 库里像谁"，所以查询图与候选
// 缩略图必须并排展示，不能只给文字结果。
export function GlyphMatchPanel({ book }: { book: string }) {
  const [page, setPage] = useState('')
  const [col, setCol] = useState('')
  const [slot, setSlot] = useState('')
  const [sub, setSub] = useState('')
  const [result, setResult] = useState<GlyphMatchResult | null>(null)
  const [msg, setMsg] = useState('')
  const [queryKey, setQueryKey] = useState<{ page: number; col: number; slot: number; sub: string } | null>(null)

  async function query() {
    const p = Number.parseInt(page, 10)
    const c = Number.parseInt(col, 10)
    const s = Number.parseInt(slot, 10)
    if (!p || !c || !s) { setMsg('页/列/格位都要填数字'); return }
    setMsg('查询中…')
    try {
      const d = await fetchGlyphMatch(book, p, c, s, sub || undefined)
      setResult(d)
      setQueryKey({ page: p, col: c, slot: s, sub })
      setMsg('')
    } catch (e) {
      setMsg((e as Error).message)
      setResult(null)
      setQueryKey(null)
    }
  }

  const queryImgSrc = queryKey
    ? `/api/cache/${encodeURIComponent(book)}/char_patch/p${String(queryKey.page).padStart(4, '0')}c${String(queryKey.col).padStart(2, '0')}s${queryKey.slot}${queryKey.sub || ''}.png`
    : ''

  const verdictLabel = { same: '继承', unsure: '候选', diff: '库里没有' } as const

  return (
    <div className="card">
      <h2>字形库匹配 <span className="muted">与 GlyphMatcher 已验证刻例逐字比对，输入字位坐标直接查</span></h2>
      <div className="gm-row">
        <label className="muted">页 <input value={page} onChange={(e) => setPage(e.target.value)} size={6} /></label>
        <label className="muted">列 <input value={col} onChange={(e) => setCol(e.target.value)} size={4} /></label>
        <label className="muted">格位 <input value={slot} onChange={(e) => setSlot(e.target.value)} size={4} /></label>
        <label className="muted">子列（夹注用，a/b，可空） <input value={sub} onChange={(e) => setSub(e.target.value)} size={3} /></label>
        <button onClick={query}>查匹配</button>
        <span className="muted">{msg}</span>
      </div>
      <p className="muted gm-help">
        same＝直接继承库里的字（cov≥0.996 且 wmax≤12）；unsure＝候选进候选集，
        与 OCR 合并交上下文裁决；diff＝库里多半没有这个字。查询不摘除自身
        （与正式识别流程的防自证不同），排查"这个字位在库里查会不会查到自己"
        用得上。
      </p>

      {result && (
        <>
          <div className="gm-compare">
            <div className="gm-compare-cell">
              <img src={queryImgSrc} alt="查询字块" />
              <div className="gm-compare-label">查询图</div>
            </div>
            {result.matched_id && (
              <div className="gm-compare-cell">
                <img src={glyphMatchExemplarUrl(result.matched_id)} alt="库里最像的刻例" />
                <div className="gm-compare-label">库里刻例 · {result.matched_id}</div>
              </div>
            )}
          </div>

          <p>
            <span className={`gm-verdict gm-verdict-${result.verdict}`}>
              {result.verdict}（{verdictLabel[result.verdict]}）
            </span>
            {' '}cov={result.cov.toFixed(4)} · wmax={result.wmax.toFixed(2)} · n_verified={result.n_verified}
            {result.guard && (
              <span className="muted">
                {' '}· 护栏：{result.guard === 'never_match' ? '形近家族拦截（护栏1）' : result.guard === 'conflict' ? '同批多字冲突（护栏2）' : result.guard}
              </span>
            )}
          </p>

          {result.candidates.length > 0 && (
            <div className="gm-cands">
              {result.candidates.map((c, i) => (
                <div className="gm-cand" key={i}>
                  {i === 0 && result.matched_id && (
                    <img src={glyphMatchExemplarUrl(result.matched_id)} alt={c.char} />
                  )}
                  <div className="gm-cand-char">{c.char}</div>
                  <div className="gm-cand-cov">cov {c.cov.toFixed(4)}</div>
                </div>
              ))}
            </div>
          )}
          {result.candidates.length === 0 && <p className="muted">没有候选（对全部 kNN 候选验证都不到 unsure 阈值）。</p>}
        </>
      )}
    </div>
  )
}
