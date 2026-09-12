import { useRef } from 'react'
import type { CandidateMatch, CutlineCase } from '../../types/cutline'

// Step7「切分裁决」板块专用卡片（overview 2026-09-11 下发）。
//
// 与 Step3 的 `CutlineCard` 故意不共用：那边是给「拖切线、攒 touching-cuts
// 金标」用的全量标注工具，这里只是「算法给了几种切法，选一个」——不需要
// 拖直线、不需要"缝正确"/"重叠·折中"/干扰标签这些跟"选哪个"无关的操作。
// 核心判据也不同：这里每个候选旁边直接摆 Step5 库匹配认出的字，跟整理本
// 期望字一比对，人一眼就能判断"选这条，两边都能认对"。
//
// 用户 2026-09-11 测试反馈追加「自己画」：候选都不对时，能画一条折线代替
// ——从 Step3 CutlineCard 移植了折线交互（点加点/拖动/右键删点），但只留
// 折线这一种手画方式，不含 Step3 的拖直线/干扰标签那些。

const CL_KIND: Record<string, string> = { straight: '直线', seam_narrow: '窄走廊', seam_wide: '宽走廊' }

interface Props {
  idx: number
  c: CutlineCase
  pick: number | null           // 当前选中的候选下标；null = 还没选
  done?: string                 // 'confirmed' | 'idk' | undefined
  isCurrent: boolean
  drawing: boolean
  poly: Array<[number, number]>
  onFocus: () => void
  onPick: (k: number) => void
  onConfirm: () => void
  onIdk: () => void
  onReopen: () => void
  onToggleDrawing: () => void
  onAddPoint: (x: number, y: number) => void
  onMovePoint: (k: number, x: number, y: number) => void
  onRemovePoint: (k: number) => void
  onClearPoly: () => void
}

function matchLabel(m: CandidateMatch | null | undefined, expect?: string) {
  if (!m) return <span className="muted">无识别</span>
  if (m.char) {
    const hit = !!(expect && m.char === expect)
    return (
      <span className={hit ? 'clm-hit' : ''}>
        {m.char} <span className="muted">{(m.cov * 100).toFixed(0)}%</span>
      </span>
    )
  }
  // unsure 档没有单一答案：库给的候选池比一个问号有用得多——期望字在
  // 候选池里也标绿，人一眼能看出"库其实认得，只是没到 same 档的把握"。
  const cands = m.candidates || []
  if (!cands.length) return <span className="muted">？ <span>{(m.cov * 100).toFixed(0)}%</span></span>
  return (
    <span className="bcc-unsure">
      {cands.map(([ch, cov], i) => (
        <span key={i} className={expect && ch === expect ? 'clm-hit' : 'muted'}>
          {ch}<span className="bcc-cov">{(cov * 100).toFixed(0)}</span>
        </span>
      ))}
    </span>
  )
}

export function BlockingCutlineCard({
  idx, c, pick, done, isCurrent, drawing, poly,
  onFocus, onPick, onConfirm, onIdk, onReopen,
  onToggleDrawing, onAddPoint, onMovePoint, onRemovePoint, onClearPoly,
}: Props) {
  const cands = c.candidates || []
  const h = c.crop_y1 - c.crop_y0
  const w = c.col_w || (c.x1 - c.x0 + 12)
  // 目标宽度收窄到 150px——这套卡片要一排放三张，不再是 Step3 那种大图单列。
  const scale = Math.min(2, Math.max(1, Math.floor((100 * 150) / w) / 100))
  const dragRef = useRef<{ k: number } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const drawn = poly.length >= 2

  function posFromEvent(ev: { clientX: number; clientY: number }) {
    const box = boxRef.current
    if (!box) return { x: 0, y: 0 }
    const rect = box.getBoundingClientRect()
    return { x: (ev.clientX - rect.left) / scale, y: c.crop_y0 + (ev.clientY - rect.top) / scale }
  }

  function nearestPoint(x: number, y: number, hitR = 9): number {
    let best = -1
    let bd = Number.POSITIVE_INFINITY
    poly.forEach(([px, py], k) => {
      const d = Math.hypot((px - x) * scale, (py - y) * scale)
      if (d < bd) { bd = d; best = k }
    })
    return bd <= hitR ? best : -1
  }

  function onMouseDown(ev: React.MouseEvent) {
    if (!drawing) return   // 外层 div 的 onClick={onFocus} 已经处理非画线模式的点击
    const { x, y } = posFromEvent(ev)
    if (ev.button === 2) {
      const k = nearestPoint(x, y)
      if (k >= 0) onRemovePoint(k)
      ev.preventDefault()
      return
    }
    const k = nearestPoint(x, y)
    if (k >= 0) dragRef.current = { k }
    else { onAddPoint(x, y); dragRef.current = { k: poly.length } }
    ev.preventDefault()
  }

  function onMouseMove(ev: React.MouseEvent) {
    if (!drawing || !dragRef.current) return
    const { x, y } = posFromEvent(ev)
    onMovePoint(dragRef.current.k, x, y)
  }

  function endDrag() { dragRef.current = null }

  const sortedPoly = poly.slice().sort((a, b) => a[0] - b[0])

  return (
    <div id={`bcc${idx}`} className={`clcard${isCurrent ? ' cur' : ''}`} data-done={done || ''}
         onClick={onFocus}>
      <div className="clhead"><b>{c.id}</b><span className="muted">p{c.page} 列{c.col} 格线{c.bi}</span></div>
      <div className="bcc-body">
        <div className="climg" ref={boxRef} style={{ height: h * scale, width: w * scale, cursor: drawing ? 'crosshair' : 'default' }}
             onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={endDrag} onMouseLeave={endDrag}
             onContextMenu={(ev) => ev.preventDefault()}>
          <img src={c.img} height={h * scale} alt={c.id} loading="lazy" style={{ width: 'auto', height: h * scale }} />
          <svg className="clsvg" style={{ height: h * scale }}>
            {cands.map((cd, k) => {
              if (!cd.y || !cd.y.length) return null
              const cls = cd.kind === 'seam_wide' ? 'wide' : 'narrow'
              return (
                <polyline key={k} className={`clcand ${cls}${k === pick && !drawn ? ' clcand-pick' : ''}`}
                          points={cd.y.map((yy, j) => `${(c.x0 + j) * scale},${(yy - c.crop_y0) * scale}`).join(' ')} />
              )
            })}
            {drawn && (
              <polyline className="clpoly" points={sortedPoly.map(([x, yy]) => `${x * scale},${(yy - c.crop_y0) * scale}`).join(' ')} />
            )}
            {poly.map(([x, yy], k) => (
              <circle key={k} className="clpt" r={5} cx={x * scale} cy={(yy - c.crop_y0) * scale} />
            ))}
          </svg>
          {!drawn && (!cands[pick ?? -1]?.y) && (
            <div className="clline" style={{ top: (c.y - c.crop_y0) * scale }} />
          )}
        </div>
        <div className="clside">
          <div className="bcc-expect">
            <span className="ch" title="上格期望字">{c.char_above || '？'}</span>
            <span className="ch" title="下格期望字">{c.char_below || '？'}</span>
            <span className="muted">← 整理本期望</span>
          </div>
          <table className="bcc-cands">
            <tbody>
              {cands.map((cd, k) => (
                <tr key={k} className={k === pick && !drawn ? 'on' : ''}
                    onClick={(e) => { e.stopPropagation(); onPick(k) }}>
                  <td className="bcc-kind">{CL_KIND[cd.kind] || cd.kind}{k === c.chosen ? ' ·现役' : ''}</td>
                  <td>{matchLabel(cd.match_above, c.char_above)}</td>
                  <td>{matchLabel(cd.match_below, c.char_below)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="clbtns">
            <button className={`clmode${drawing ? ' on' : ''}`}
                    onClick={(e) => { e.stopPropagation(); onToggleDrawing() }}>
              {drawn ? '✓ 自己画' : '自己画'}
            </button>
            {poly.length > 0 && (
              <button onClick={(e) => { e.stopPropagation(); onClearPoly() }}>清空</button>
            )}
            <button className={done === 'confirmed' ? 'on' : ''} disabled={pick == null && !drawn}
                    onClick={onConfirm}>落定</button>
            <button className={done === 'idk' ? 'on' : ''} onClick={onIdk}>拿不准</button>
            {done && <button onClick={onReopen}>重做</button>}
          </div>
          {drawing && <span className="muted bcc-drawhint">点空白加点·拖点移动·右键删点</span>}
        </div>
      </div>
    </div>
  )
}
