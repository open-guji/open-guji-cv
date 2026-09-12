import { useRef, useState } from 'react'
import type { PageLineCard as Card } from '../../types/borderPageLine'

export interface OffsetState {
  offset: number
  done?: string
}

interface Props {
  idx: number
  c: Card
  st: OffsetState
  isCurrent: boolean
  onFocus: () => void
  onSetOffset: (offset: number) => void
  onDecide: (verdict: string) => void
}

// 通栏带图宽度不固定（原图整宽），高度是 render_pageline_img 裁出来的窄带
// （PAGE_BAND_MARGIN 两侧各留 150px）。图按容器宽度铺满，纵向按同一比例
// 缩放（naturalHeight/naturalWidth 保持原图长宽比），线的两端点跟着缩放
// 系数换算，拖动只在垂直方向加一个统一偏移（保留现役斜率）。
export function PageLineCard({ idx, c, st, isCurrent, onFocus, onSetOffset, onDecide }: Props) {
  const [dispW, setDispW] = useState(0)
  const [naturalW, setNaturalW] = useState(0)
  const dragging = useRef(false)
  const dragStartY = useRef(0)
  const dragStartOffset = useRef(0)

  const scale = naturalW > 0 ? dispW / naturalW : 1

  function onMouseDown(ev: React.MouseEvent) {
    onFocus()
    dragging.current = true
    dragStartY.current = ev.clientY
    dragStartOffset.current = st.offset
    ev.preventDefault()
  }

  function onMouseMove(ev: React.MouseEvent) {
    if (!dragging.current) return
    const dy = (ev.clientY - dragStartY.current) / (scale || 1)
    onSetOffset(dragStartOffset.current + dy)
  }

  function endDrag() {
    dragging.current = false
  }

  const yL = (c.y_left + st.offset) * scale
  const yR = (c.y_right + st.offset) * scale
  const yL0 = c.y_left * scale
  const yR0 = c.y_right * scale

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
          </svg>
        )}
      </div>
      <div className="bl-info muted">偏移 = {st.offset.toFixed(1)}px（正值＝线下移，负值＝上移）</div>
      <div className="br-verdicts">
        <button title="回车" aria-pressed={st.done === 'moved'} onClick={() => onDecide('moved')}>落定此偏移</button>
        <button title="O" aria-pressed={st.done === 'ok'} onClick={() => onDecide('ok')}>现役线位置就对</button>
        <button title="N" aria-pressed={st.done === 'no_line'} onClick={() => onDecide('no_line')}>看不出线</button>
      </div>
    </article>
  )
}
