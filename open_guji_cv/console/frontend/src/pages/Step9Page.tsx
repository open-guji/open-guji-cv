import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchStep9Render } from '../api/step9'
import { PageRangeSelector, loadSavedPageRange } from '../components/common/PageRangeSelector'
import type { Step9RenderResponse } from '../api/step9'

// Step9 结果整理 · 坐标转字符位（2026-09-11）。三件事里只有这一件落地——
// 体检表、与整理本比对还没做，见 overview 仓 Step9-结果整理/README.md §二。
//
// **不进管线**：这不是"选一页看它的产物"（那是 ProductViewer 的活，Step9
// 也没有对应的后端 Step id），是**现场触发一次渲染**——用户 2026-09-11
// 明确要求"允许审阅一半时直接输出看看效果"，所以每次点"生成"都是当场
// join Step3+Step7 产物现算，不落盘、不进队列，也没有进度条（页数大就会等
// 得久，别选整册）。
export function Step9Page() {
  const { book = '' } = useParams()
  const [pageSel, setPageSel] = useState(() => loadSavedPageRange('step9', book, ''))
  const [result, setResult] = useState<Step9RenderResponse | null>(null)
  const [msg, setMsg] = useState('')

  async function generate() {
    if (!pageSel.trim()) {
      setMsg('先填页范围（单页如 "33"，或 "10,33,89"、"33-40"）')
      return
    }
    setMsg('渲染中…')
    setResult(null)
    try {
      setResult(await fetchStep9Render(book, pageSel))
      setMsg('')
    } catch (e) {
      setMsg('渲染失败：' + (e as Error).message)
    }
  }

  return (
    <div>
      <div className="card">
        <h2>Step9 结果整理 <span className="muted">坐标转字符位，现场渲染，不进管线</span></h2>
        <p className="muted">
          把 Step3（版面结构）＋ Step7（定字结果）拼成 guji-markdown 文本。
          审阅还没全部完成时也能用——挑几页现看效果，不影响整册流程。
        </p>
      </div>
      <PageRangeSelector book={book} stepId="step9" value={pageSel} onChange={setPageSel} />
      <div className="card">
        <button onClick={generate}>生成</button>
        {msg && <span className="muted" style={{ marginLeft: '.8rem' }}>{msg}</span>}
      </div>
      {result && (
        <div className="card">
          <h3>结果 <span className="muted">{result.pages.length} 页</span></h3>
          {result.stale.length > 0 && (
            <p className="muted" style={{ color: '#b45309' }}>
              ⚠ {result.stale.length} 处 Step7 记录在 Step3 里查不到对应格子
              （多半是这一页 Step3 局部重切后 Step7 没跟着重跑，产物过期）：
              {' '}{result.stale.join(', ')}
            </p>
          )}
          <pre className="json">{result.text}</pre>
        </div>
      )}
    </div>
  )
}
