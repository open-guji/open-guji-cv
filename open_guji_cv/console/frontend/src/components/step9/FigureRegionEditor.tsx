import { useEffect, useRef, useState } from 'react'
import {
  fetchFigurePage, fetchFigurePages, rawPageUrl, saveFigurePage,
  type FigurePage, type FigureRegion,
} from '../../api/figureRegion'

// 插图块画框（GUJI-737，2026-10-24）：占几列、半页或整页的插图，在页图上拖一个框、写一句说明，存成
// `figure_region` 事件。Step9 导出读它：被占的列换成图列，从页图裁出 WebP。
// 判准（先看能不能写成字；看不清不是图）见 cv `doc/design/图片格与插图-处理流程.md`。
// 占一格的小图形不在这里画，在精校卡上选「是图形，不是字」。
//
// 交互：页图上按住拖出框；框上方的列号、列数由后端按「盖住某列宽度一半以上」算，列上没有字框（整页插图常见）
// 就自己填。存是整页覆盖，删光再存 = 撤掉本页插图块。

const IMG_SCALE = 0.35        // 原图缩小再传，够看清版面

interface Draft extends FigureRegion {
  key: number
}

let nextKey = 1

export function FigureRegionEditor({ book }: { book: string }) {
  const [pageInput, setPageInput] = useState('')
  const [data, setData] = useState<FigurePage | null>(null)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [msg, setMsg] = useState('')
  const [pagesWith, setPagesWith] = useState<string[]>([])
  const [dispW, setDispW] = useState(0)
  const drag = useRef<{ x0: number; y0: number } | null>(null)
  const [live, setLive] = useState<[number, number, number, number] | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  const s = data && dispW ? dispW / data.width : 0      // canvas 像素 → 屏幕像素

  async function refreshList() {
    try {
      setPagesWith(Object.keys((await fetchFigurePages(book)).pages).sort((a, b) => Number(a) - Number(b)))
    } catch { /* 列表取不到不挡画框 */ }
  }

  useEffect(() => { refreshList() }, [book])  // 换册重读已画页列表

  async function load(pg?: number) {
    const page = pg ?? Number(pageInput)
    if (!Number.isInteger(page) || page < 1) {
      setMsg('先填页号')
      return
    }
    setMsg('读取中…')
    setData(null)
    setDispW(0)
    try {
      const d = await fetchFigurePage(book, page)
      setData(d)
      setDrafts(d.regions.map((r) => ({ ...r, key: nextKey++ })))
      setPageInput(String(page))
      setMsg('')
    } catch (e) {
      setMsg('读取失败：' + (e as Error).message)
    }
  }

  function toCanvas(ev: React.MouseEvent): [number, number] {
    const rect = boxRef.current!.getBoundingClientRect()
    return [(ev.clientX - rect.left) / s, (ev.clientY - rect.top) / s]
  }

  function onDown(ev: React.MouseEvent) {
    if (!s) return
    const [x, y] = toCanvas(ev)
    drag.current = { x0: x, y0: y }
    setLive([x, y, 0, 0])
    ev.preventDefault()
  }

  function onMove(ev: React.MouseEvent) {
    const d = drag.current
    if (!d) return
    const [x, y] = toCanvas(ev)
    setLive([Math.min(d.x0, x), Math.min(d.y0, y), Math.abs(x - d.x0), Math.abs(y - d.y0)])
  }

  function onUp() {
    const box = live
    drag.current = null
    setLive(null)
    if (!box || box[2] * s < 8 || box[3] * s < 8) return      // 点一下不算
    setDrafts((ds) => [...ds, { key: nextKey++, box: box.map(Math.round) as Draft['box'], alt: '' }])
  }

  function patch(key: number, p: Partial<Draft>) {
    setDrafts((ds) => ds.map((d) => (d.key === key ? { ...d, ...p } : d)))
  }

  async function save() {
    if (!data) return
    setMsg('保存中…')
    try {
      const regions = drafts.map(({ key: _k, ...r }) => r)
      const out = await saveFigurePage(book, data.page, regions)
      setDrafts(out.regions.map((r) => ({ ...r, key: nextKey++ })))
      setMsg(out.regions.length ? `已存 ${out.regions.length} 块（列号已按框算好）` : '已撤掉本页插图块')
      refreshList()
    } catch (e) {
      setMsg('没存：' + (e as Error).message)
    }
  }

  const numOrUndef = (v: string) => (v.trim() === '' ? undefined : Number(v))

  return (
    <div className="card figreg">
      <h2>插图块 <span className="muted">占几列、半页或整页的插图：在页图上拖框，写一句说明</span></h2>
      <p className="muted">
        占一格的小图形不在这里画，在精校卡上选「是图形，不是字」。先看能不能写成字；看不清的字仍是阙文，不是图。
        存是整页覆盖；导出（S17）时被占的列换成图，从页图裁出。
      </p>
      <div className="figreg-bar">
        <label>页 <input value={pageInput} onChange={(e) => setPageInput(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') load() }} style={{ width: '4.5rem' }} /></label>
        <button onClick={() => load()}>打开</button>
        {pagesWith.length > 0 && (
          <span className="muted">已画：{pagesWith.map((p) => (
            <a key={p} href="#" onClick={(e) => { e.preventDefault(); load(Number(p)) }} style={{ marginRight: '.4rem' }}>{p}</a>
          ))}</span>
        )}
        {msg && <span className="muted">{msg}</span>}
      </div>

      {data && (
        <div className="figreg-body">
          <div className="figreg-img" ref={boxRef}
               onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
            <img src={rawPageUrl(book, data.page, IMG_SCALE)} alt={`第 ${data.page} 页`} draggable={false}
                 onLoad={(e) => setDispW(e.currentTarget.clientWidth)} />
            {s > 0 && (
              <svg className="figreg-svg" width={dispW} height={data.height * s}>
                {data.columns.map((c) => (
                  <g key={c.col}>
                    <rect className="figreg-col" x={c.x * s} y={0} width={c.w * s} height={data.height * s} />
                    <text className="figreg-colno" x={(c.x + c.w / 2) * s} y={12}>{c.col}</text>
                  </g>
                ))}
                {drafts.map((d, i) => (
                  <g key={d.key}>
                    <rect className="figreg-box" x={d.box[0] * s} y={d.box[1] * s} width={d.box[2] * s} height={d.box[3] * s} />
                    <text className="figreg-boxno" x={d.box[0] * s + 4} y={d.box[1] * s + 16}>{i + 1}</text>
                  </g>
                ))}
                {live && <rect className="figreg-box live" x={live[0] * s} y={live[1] * s} width={live[2] * s} height={live[3] * s} />}
              </svg>
            )}
          </div>
          <div className="figreg-list">
            {drafts.length === 0 && <p className="muted">本页还没有插图块。在左边页图上按住拖出一个框。</p>}
            {drafts.map((d, i) => (
              <div key={d.key} className="figreg-item">
                <b>{i + 1}</b>
                <label>说明 <input value={d.alt} maxLength={60} placeholder="写形状，如「河圖」「九宫图」"
                                 onChange={(e) => patch(d.key, { alt: e.target.value })} /></label>
                <label>列 <input value={d.col ?? ''} placeholder="自动" style={{ width: '3rem' }}
                                onChange={(e) => patch(d.key, { col: numOrUndef(e.target.value) })} /></label>
                <label>占 <input value={d.span ?? ''} placeholder="自动" style={{ width: '3rem' }}
                                onChange={(e) => patch(d.key, { span: numOrUndef(e.target.value) })} /> 列</label>
                <button onClick={() => setDrafts((ds) => ds.filter((x) => x.key !== d.key))}>删</button>
                <span className="muted">框 {d.box.join(', ')}</span>
              </div>
            ))}
            <button className="primary" onClick={save}>存本页</button>
          </div>
        </div>
      )}
    </div>
  )
}
