import { useRef, useState } from 'react'
import type { BorderLineCard as Card } from '../../types/borderLine'

export interface LineState {
  y: number
  done?: string
}

interface Props {
  c: Card
  st: LineState
  onSetY: (y: number) => void
  onDecide: (verdict: string) => void
}

// 图是服务端现算的 jpg（裁剪图 + 拼接的投影带），宽度不固定，靠 onLoad 读
// naturalHeight 换算显示高度——照抄 CutlineCard 的思路，但这里没有服务端
// 传回的 col_w，只能等图加载完才知道要按多大比例拖线。
export function BorderLineCard({ c, st, onSetY, onDecide }: Props) {
  const [dispH, setDispH] = useState(0)
  const [naturalH, setNaturalH] = useState(0)
  const dragging = useRef(false)
  const boxRef = useRef<HTMLDivElement>(null)

  const scale = naturalH > 0 ? dispH / naturalH : 1

  function yFromEvent(ev: { clientY: number }): number {
    const box = boxRef.current
    if (!box || naturalH === 0) return st.y
    const rect = box.getBoundingClientRect()
    return Math.max(0, Math.min(c.col_h, (ev.clientY - rect.top) / scale))
  }

  function onMouseDown(ev: React.MouseEvent) {
    dragging.current = true
    onSetY(yFromEvent(ev))
    ev.preventDefault()
  }

  function onMouseMove(ev: React.MouseEvent) {
    if (!dragging.current) return
    onSetY(yFromEvent(ev))
  }

  function endDrag() {
    dragging.current = false
  }

  return (
    <article className="brcard blcard" data-v={st.done || ''}>
      <h3>{c.book}/{c.page} <em>第 {c.col} 列 · 下端{c.raised ? '（抬头列）' : ''}</em></h3>
      <div className="blimg" ref={boxRef} style={{ height: dispH || undefined }}
           onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={endDrag} onMouseLeave={endDrag}>
        <img src={c.img} alt="" loading="lazy" className="br-img-pixelated"
             onLoad={(ev) => {
               const img = ev.currentTarget
               setNaturalH(img.naturalHeight)
               setDispH(Math.min(440, img.naturalHeight * Math.min(2, 420 / img.naturalWidth)))
             }} />
        {naturalH > 0 && (
          <>
            <div className="blline old" style={{ top: c.y0 * scale }} title={`BOTTOM_PAD 假设位置 y=${c.y0}`} />
            <div className="blline" style={{ top: st.y * scale }} title={`当前 y=${st.y.toFixed(1)}`} />
          </>
        )}
      </div>
      <div className="bl-info muted">y = {st.y.toFixed(1)} · Δ算法 {(st.y - c.y0).toFixed(1)}px</div>
      <div className="br-verdicts">
        <button aria-pressed={st.done === 'moved'} onClick={() => onDecide('moved')}>落定此线</button>
        <button aria-pressed={st.done === 'ok'} onClick={() => onDecide('ok')}>淡色线位置就对</button>
        <button aria-pressed={st.done === 'no_line'} onClick={() => onDecide('no_line')}>看不出线</button>
      </div>
    </article>
  )
}
