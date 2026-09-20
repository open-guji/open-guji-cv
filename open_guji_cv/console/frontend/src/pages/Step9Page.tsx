import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchStep9Reflow, fetchStep9Render } from '../api/step9'
import { PageRangeSelector, loadSavedPageRange } from '../components/common/PageRangeSelector'
import type { Step9ReflowResponse, Step9RenderResponse } from '../api/step9'

const BASELINE_KEY_PREFIX = 'guji-step9-baseline:'

function loadSavedBaseline(book: string): number {
  if (!book) return 2
  try {
    const v = localStorage.getItem(BASELINE_KEY_PREFIX + book)
    return v ? Number(v) : 2
  } catch {
    return 2
  }
}

function saveBaseline(book: string, v: number): void {
  if (!book) return
  try {
    localStorage.setItem(BASELINE_KEY_PREFIX + book, String(v))
  } catch { /* 隐私模式等，忽略 */ }
}

type View = 'render' | 'reflow'

// Step3/Step7 对不上的格。文案别再写死成"产物过期"——**单行小字注**那一型
// （Step3 按几何记 sub='a'、Step7 按「一个字」记 sub=None）本来占了实测里的
// 绝大多数，2026-09-19 已在 `report/slots.py::_lookup_cell` 认回来、不再进这个
// 列表；剩下能走到这儿的才是真过期。但"多半是…"这种口气当初就是只见过一个
// 个例时写的，害人白重跑一轮 Step7，所以这里只陈述现象＋给一条可验证的下一步，
// 不替人断因。
function StaleWarning({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <p className="reflow-stale">
      ⚠ {items.length} 处 Step7 记录在 Step3 里查不到对应格子，已按正文字兜底出字
      （字不会丢，但这些格的夹注/留白身份是猜的）。
      先跑 <code>guji status</code> 看这几页是不是标了"过期"：是就重跑 Step3→Step7，
      不是则属新成因，别急着重跑，先看一眼这几格的实际版面。
      {' '}{items.join(', ')}
    </p>
  )
}

// Step9 结果整理：9.1 坐标转字符位 ＋ 9.2 可阅读排版（2026-09-12）。
// 体检表、与整理本比对还没做，见 overview 仓 Step9-结果整理/README.md §二。
//
// **不进管线**：这不是"选一页看它的产物"（那是 ProductViewer 的活，Step9
// 也没有对应的后端 Step id），是**现场触发一次渲染**——用户 2026-09-11
// 明确要求"允许审阅一半时直接输出看看效果"，所以每次点"生成"都是当场
// join Step3+Step7 产物现算，不落盘、不进队列，也没有进度条（页数大就会等
// 得久，别选整册）。
//
// 两个视图（tab）各自独立触发，不强制"先跑9.1才能跑9.2"——9.2 内部会
// 自己重新调用 render_page，两条链路互不依赖对方是否已经点过"生成"。
export function Step9Page() {
  const { book = '' } = useParams()
  const [pageSel, setPageSel] = useState(() => loadSavedPageRange('step9', book, ''))
  const [baselineKg, setBaselineKg] = useState(() => loadSavedBaseline(book))
  const [view, setView] = useState<View>('render')

  const [renderResult, setRenderResult] = useState<Step9RenderResponse | null>(null)
  const [renderMsg, setRenderMsg] = useState('')
  const [reflowResult, setReflowResult] = useState<Step9ReflowResponse | null>(null)
  const [reflowMsg, setReflowMsg] = useState('')

  function setBaseline(v: number) {
    setBaselineKg(v)
    saveBaseline(book, v)
  }

  async function generate() {
    if (!pageSel.trim()) {
      const msg = '先填页范围（单页如 "33"，或 "10,33,89"、"33-40"）'
      setRenderMsg(msg)
      setReflowMsg(msg)
      return
    }
    if (view === 'render') {
      setRenderMsg('渲染中…')
      setRenderResult(null)
      try {
        setRenderResult(await fetchStep9Render(book, pageSel))
        setRenderMsg('')
      } catch (e) {
        setRenderMsg('渲染失败：' + (e as Error).message)
      }
    } else {
      setReflowMsg('排版中…')
      setReflowResult(null)
      try {
        setReflowResult(await fetchStep9Reflow(book, pageSel, baselineKg))
        setReflowMsg('')
      } catch (e) {
        setReflowMsg('排版失败：' + (e as Error).message)
      }
    }
  }

  const totalNotes = reflowResult?.pages.reduce((n, p) => n + p.notes.length, 0) ?? 0
  const totalParas = reflowResult?.pages.reduce((n, p) => n + p.paragraphs.length, 0) ?? 0

  return (
    <div>
      <div className="card">
        <h2>Step9 结果整理 <span className="muted">现场渲染，不进管线</span></h2>
        <p className="muted">
          9.1 把 Step3（版面结构）＋ Step7（定字结果）拼成 guji-markdown 文本；
          9.2 在此基础上取消版式记号、按规则分段，拼成可阅读的横排文本。
          审阅还没全部完成时也能用——挑几页现看效果，不影响整册流程。
        </p>
      </div>

      <PageRangeSelector book={book} stepId="step9" value={pageSel} onChange={setPageSel} />

      <div className="tabs">
        <button className={view === 'render' ? 'active' : ''} onClick={() => setView('render')}>
          9.1 坐标转字符位
        </button>
        <button className={view === 'reflow' ? 'active' : ''} onClick={() => setView('reflow')}>
          9.2 可阅读排版
        </button>
      </div>

      {view === 'reflow' && (
        <div className="card">
          <label className="muted">
            基线挪抬点数{' '}
            <input type="number" min={0} max={9} value={baselineKg}
                   onChange={(e) => setBaseline(Number(e.target.value))}
                   style={{ width: '3.5rem' }}
                   title="这一批页面正文行正常的挪抬点数（已知常量，不是猜的），常见取值 1~4" />
          </label>
          <span className="muted" style={{ marginLeft: '.6rem' }}>
            全书统一或按段落各不相同，先按经验值填，效果不对再调
          </span>
        </div>
      )}

      <div className="card">
        <button className="primary" onClick={generate}>生成</button>
        {view === 'render' && renderMsg && <span className="muted" style={{ marginLeft: '.8rem' }}>{renderMsg}</span>}
        {view === 'reflow' && reflowMsg && <span className="muted" style={{ marginLeft: '.8rem' }}>{reflowMsg}</span>}
      </div>

      {view === 'render' && renderResult && (
        <div className="card">
          <h3 style={{ margin: '0 0 .6rem', fontSize: '.95rem' }}>
            结果 <span className="muted">{renderResult.pages.length} 页</span>
          </h3>
          <StaleWarning items={renderResult.stale} />
          <pre className="json">{renderResult.text}</pre>
        </div>
      )}

      {view === 'reflow' && reflowResult && (
        <div className="card">
          <h3 style={{ margin: '0 0 .6rem', fontSize: '.95rem' }}>
            结果 <span className="muted">
              {reflowResult.pages.length} 页 · {totalParas} 段
              {totalNotes > 0 && <> · {totalNotes} 处标记供复核</>}
            </span>
          </h3>
          <StaleWarning items={reflowResult.stale} />
          {reflowResult.pages.map((pg) => (
            <div key={pg.page}>
              <div className="reflow-page-mark">第 {pg.page} 页</div>
              {pg.paragraphs.length === 0 && <p className="muted">（本页无正文列）</p>}
              {pg.paragraphs.map((para, i) => (
                <p key={i} className={'reflow-para' + (para.is_title ? ' is-title' : '')}>
                  {para.text}
                </p>
              ))}
              {pg.notes.length > 0 && (
                <details className="reflow-notes">
                  <summary>{pg.notes.length} 处标记供复核</summary>
                  <ul>
                    {pg.notes.map((n, i) => <li key={i}>{n}</li>)}
                  </ul>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
