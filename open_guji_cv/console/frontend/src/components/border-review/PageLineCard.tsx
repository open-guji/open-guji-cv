import { useRef, useState } from 'react'
import type { PageLineCard as Card } from '../../types/borderPageLine'

export interface LineState {
  yLeft: number
  yRight: number
  done?: string
}

interface Props {
  idx: number
  c: Card
  st: LineState
  isCurrent: boolean
  onFocus: () => void
  onSetLine: (yLeft: number, yRight: number) => void
  onDecide: (verdict: string) => void
}

const HANDLE_HIT_PX = 14

// 通栏带图宽度不固定（原图整宽），高度是 render_pageline_img 裁出来的窄带
// （PAGE_BAND_MARGIN 两侧各留 150px）。图按容器宽度铺满，纵向按同一比例
// 缩放。线两端各有一个可独立拖拽的手柄——版框本身可能是斜的，也可能
// 现役斜率本身就探错了，光能整体平移改不了斜率，两端点必须能各自调整。
// 拖手柄附近（HANDLE_HIT_PX 内）只动那一端；拖线身其余位置整体平移
// （两端同步），方便先粗调再到端点精修。
export function PageLineCard({ idx, c, st, isCurrent, onFocus, onSetLine, onDecide }: Props) {
  const [dispW, setDispW] = useState(0)
  const [naturalW, setNaturalW] = useState(0)
  const drag = useRef<{ mode: 'left' | 'right' | 'both'; startY: number; startLeft: number; startRight: number } | null>(null)

  const scale = naturalW > 0 ? dispW / naturalW : 1
  const yL = st.yLeft * scale
  const yR = st.yRight * scale
  const yL0 = c.y_left * scale
  const yR0 = c.y_right * scale

  function onMouseDown(ev: React.MouseEvent) {
    onFocus()
    const rect = ev.currentTarget.getBoundingClientRect()
    const localX = ev.clientX - rect.left
    const localY = ev.clientY - rect.top
    const distLeft = Math.hypot(localX - 0, localY - yL)
    const distRight = Math.hypot(localX - dispW, localY - yR)
    let mode: 'left' | 'right' | 'both' = 'both'
    if (distLeft <= HANDLE_HIT_PX) mode = 'left'
    else if (distRight <= HANDLE_HIT_PX) mode = 'right'
    drag.current = { mode, startY: ev.clientY, startLeft: st.yLeft, startRight: st.yRight }
    ev.preventDefault()
  }

  function onMouseMove(ev: React.MouseEvent) {
    const d = drag.current
    if (!d) return
    const dy = (ev.clientY - d.startY) / (scale || 1)
    if (d.mode === 'left') onSetLine(d.startLeft + dy, st.yRight)
    else if (d.mode === 'right') onSetLine(st.yLeft, d.startRight + dy)
    else onSetLine(d.startLeft + dy, d.startRight + dy)
  }

  function endDrag() {
    drag.current = null
  }

  return (
    <article id={`plc${idx}`} className={`brcard plcard${isCurrent ? ' cur' : ''}`} data-v={st.done || ''}>
      <h3>{c.book}/{c.page}</h3>
      <div className="plimg"
           onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={endDrag} onMouseLeave={endDrag}>
        <img src={c.img} alt="" loading="lazy"
             onLoad={(ev) => {
               const img = ev.currentTarget
               setNaturalW(img.naturalWidth)
               setDispW(img.clientWidth)
             }} />
        {naturalW > 0 && (
          <svg className="plsvg">
            <line className="plline old" x1={0} y1={yL0} x2={dispW} y2={yR0} />
            <line className="plline" x1={0} y1={yL} x2={dispW} y2={yR} />
            <circle className="plhandle" cx={0} cy={yL} r={6} />
            <circle className="plhandle" cx={dispW} cy={yR} r={6} />
          </svg>
        )}
      </div>
      <div className="bl-info muted">
        左端 Δ{(st.yLeft - c.y_left).toFixed(1)}px · 右端 Δ{(st.yRight - c.y_right).toFixed(1)}px
      </div>
      <div className="br-verdicts">
        <button title="回车" aria-pressed={st.done === 'moved'} onClick={() => onDecide('moved')}>落定此线</button>
        <button title="O" aria-pressed={st.done === 'ok'} onClick={() => onDecide('ok')}>现役线位置就对</button>
        <button title="N" aria-pressed={st.done === 'no_line'} onClick={() => onDecide('no_line')}>看不出线</button>
      </div>
    </article>
  )
}
