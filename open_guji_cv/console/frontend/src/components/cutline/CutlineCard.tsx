import { useRef } from 'react'
import { withWorkspace } from '../../api/client'
import type { CutlineCase } from '../../types/cutline'

export interface CardState {
  y: number
  mode: 'line' | 'poly'
  poly: Array<[number, number]>
  pick: number
  /** 人主动点过切法（回车即按所选切法落定） */
  pickTouched?: boolean
  tags: Record<string, boolean>
  done?: string
  hidden: boolean
}

const CL_KIND: Record<string, string> = { straight: '直线', seam_narrow: '窄走廊', seam_wide: '宽走廊', unet_seam: 'U-Net缝', period_up: '按格高↑', period_dn: '按格高↓' }
// 候选线一条一色（2026-09-15：L3 扩池后一张卡可能有 6 条候选，原来只有两种颜色、选中也不高亮，人分不出点了哪条）。
// 按**池内下标**取色，与右侧按钮上的色点一一对应；选中的那条画成实线加粗。
// Step7 的 BlockingCutlineCard 也用这一套（两处卡片的候选色必须一致，否则
// 同一条候选在两个面板里颜色不同，人对不上号）。
export const CL_COLORS = ['#2f6fb5', '#c47f17', '#1f9e78', '#b5484e', '#7a5bbd', '#0f8ea8']

// 每张卡自己的显示倍率，照抄 v1 clScale：列图裁片原宽约 180-210px，
// 放到 ≤300px 且 ≤2 倍，卡片再窄也不会把右侧按钮挤没。
function scaleOf(c: CutlineCase): number {
  const w = c.col_w || (c.x1 - c.x0 + 12)
  return Math.min(2, Math.max(1, Math.floor((100 * 300) / w) / 100))
}

interface Props {
  idx: number
  c: CutlineCase
  st: CardState
  isCurrent: boolean
  onFocus: () => void
  onSetY: (y: number) => void
  onAddPoint: (x: number, y: number) => void
  onMovePoint: (k: number, x: number, y: number) => void
  onRemovePoint: (k: number) => void
  onDecide: (verdict: string) => void
  onPick: (k: number) => void
  onToggleMode: () => void
  onClearPoly: () => void
  onReopen: () => void
  onToggleTag: (t: string) => void
}

export function CutlineCard({
  idx, c, st, isCurrent, onFocus, onSetY, onAddPoint, onMovePoint, onRemovePoint,
  onDecide, onPick, onToggleMode, onClearPoly, onReopen, onToggleTag,
}: Props) {
  const s = scaleOf(c)
  const h = c.crop_y1 - c.crop_y0
  const cands = c.candidates || []
  const dragRef = useRef<{ mode: 'line' } | { mode: 'point'; k: number } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  function posFromEvent(ev: { clientX: number; clientY: number }) {
    const box = boxRef.current
    if (!box) return { x: 0, y: 0 }
    const rect = box.getBoundingClientRect()
    return {
      x: (ev.clientX - rect.left) / s,
      y: c.crop_y0 + (ev.clientY - rect.top) / s,
    }
  }

  function nearestPoint(x: number, y: number, hitR = 9): number {
    let best = -1
    let bd = Number.POSITIVE_INFINITY
    st.poly.forEach(([px, py], k) => {
      const d = Math.hypot((px - x) * s, (py - y) * s)
      if (d < bd) { bd = d; best = k }
    })
    return bd <= hitR ? best : -1
  }

  function onMouseDown(ev: React.MouseEvent) {
    onFocus()
    const { x, y } = posFromEvent(ev)
    if (st.mode === 'poly') {
      if (ev.button === 2) {
        const k = nearestPoint(x, y)
        if (k >= 0) onRemovePoint(k)
        ev.preventDefault()
        return
      }
      const k = nearestPoint(x, y)
      if (k >= 0) {
        dragRef.current = { mode: 'point', k }
      } else {
        onAddPoint(x, y)
        dragRef.current = { mode: 'point', k: st.poly.length }
      }
      ev.preventDefault()
      return
    }
    dragRef.current = { mode: 'line' }
    onSetY(y)
    ev.preventDefault()
  }

  function onMouseMove(ev: React.MouseEvent) {
    const d = dragRef.current
    if (!d) return
    const { x, y } = posFromEvent(ev)
    if (d.mode === 'point') onMovePoint(d.k, x, y)
    else onSetY(y)
  }

  function endDrag() {
    dragRef.current = null
  }

  const pickRow = cands.length > 1 ? (
    <div className="clbtns clcandbtns" title="算法给的几种切法：点一种选中（图上同色线加粗），再按「切法正确」">
      <div className="clcandlist">
        {cands.map((cd, k) => (
          <button key={k} className={`clcandbtn${k === st.pick ? ' on' : ''}`}
                  style={{ ['--cc' as string]: CL_COLORS[k % CL_COLORS.length] }}
                  title={`墨 ${cd.seam_ink} · 离直线 ${cd.dev_max}px${cd.agree != null ? ` · 与 U-Net 一致 ${(cd.agree * 100).toFixed(1)}%` : ''}${cd.dis_unet != null ? ` · 分歧块 ${cd.dis_unet}px` : ''}`}
                  onClick={() => onPick(k)}>
            <i className="cldot" />
            <span className="clk">{CL_KIND[cd.kind] || cd.kind}</span>
            <span className="muted">墨{cd.seam_ink}·偏{cd.dev_max}{cd.dis_unet != null ? `·歧${cd.dis_unet}` : ''}</span>
          </button>
        ))}
      </div>
    </div>
  ) : null

  const pickedCand = cands[st.pick]
  const candDisabled = !(st.pick > 0 && pickedCand && pickedCand.y)

  const sortedPoly = st.poly.slice().sort((a, b) => a[0] - b[0])

  return (
    <div id={`clc${idx}`} className={`clcard${isCurrent ? ' cur' : ''}`} data-done={st.done || ''}>
      <div className="clhead"><b>{c.id}</b><span className="muted">p{c.page} 列{c.col} 格线{c.bi} · 墨 {c.ink}</span></div>
      <div className="clbody">
        <div className="climg" ref={boxRef} style={{ height: h * s, cursor: st.mode === 'poly' ? 'crosshair' : 'ns-resize' }}
             onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={endDrag} onMouseLeave={endDrag}
             onContextMenu={(ev) => ev.preventDefault()}>
          {/* 同 ReviewCardView：图片出口的工作区只能放查询串 */}
          <img src={withWorkspace(c.img)} height={h * s} alt={c.id} loading="lazy" style={{ width: 'auto', height: h * s }} />
          <div className="clline old" style={{ top: (c.y - c.crop_y0) * s }} />
          <div className="clline" style={{ top: (st.y - c.crop_y0) * s }} />
          <svg className="clsvg" style={{ height: h * s }}>
            {c.seam && c.seam.length > 0 && (
              <polyline className="clseam" points={c.seam.map((yy, k) => `${(c.x0 + k) * s},${(yy - c.crop_y0) * s}`).join(' ')} />
            )}
            {cands.map((cd, k) => {
              const pts = (cd.y && cd.y.length)
                ? cd.y.map((yy, j) => `${(c.x0 + j) * s},${(yy - c.crop_y0) * s}`).join(' ')
                // 直线候选没有逐列 y：按切点位置画一条横线，否则它在图上根本不显示，人无从比较
                : `${c.x0 * s},${(c.y - c.crop_y0) * s} ${c.x1 * s},${(c.y - c.crop_y0) * s}`
              return (
                <polyline key={k} className={`clcand${k === st.pick ? ' clcand-pick' : ''}`}
                          stroke={CL_COLORS[k % CL_COLORS.length]} points={pts} />
              )
            })}
            <polyline className="clpoly" points={sortedPoly.map(([x, yy]) => `${x * s},${(yy - c.crop_y0) * s}`).join(' ')} />
            {sortedPoly.map(([x, yy], k) => (
              <circle key={k} className="clpt" r={5} cx={x * s} cy={(yy - c.crop_y0) * s} />
            ))}
          </svg>
        </div>
        <div className="clside">
          <div className="clpair">
            <span><span className="ch" title="上格期望字">{c.char_above || '？'}</span><span className="muted">上格 {c.slot_above}</span></span>
            <span><span className="ch" title="下格期望字">{c.char_below || '？'}</span><span className="muted">下格 {c.slot_below}</span></span>
            <span className="dy" title="当前线相对现役切点的偏移">Δ {st.y - c.y}px</span>
          </div>

          <div className="clgroup">
            <div className="clcap">判定 <span className="muted">点一个即落定</span></div>
            {pickRow}
            <div className="clbtns">
              <button title="O：现役切点（蓝虚线）位置就对" className={st.done === 'ok' ? 'on' : ''} onClick={() => onDecide('ok')}>现切点正确<kbd>O</kbd></button>
              <button title="回车：把线拖到理想位置后落定（= moved；没动过 = 现切点正确）" className={st.done === 'moved' ? 'on' : ''} onClick={() => onDecide('moved')}>拖线落定<kbd>↵</kbd></button>
              <button title="G：绿色虚线（现役折线缝）已经是理想切法，直接记为折线金标" disabled={!c.seam}
                      className={st.done === 'seam_ok' ? 'on' : ''} onClick={() => onDecide('seam_ok')}>缝正确<kbd>G</kbd></button>
              {cands.length > 1 && (
                <button title="C：按上面选中的那条算法候选线落定，直接记为折线金标" disabled={candDisabled}
                        className={st.done === 'cand' ? 'on' : ''} onClick={() => onDecide('cand')}>切法正确<kbd>C</kbd></button>
              )}
              <button title="V：上下字重叠、切在哪都伤字，线放折中处" className={st.done === 'overlap' ? 'on' : ''} onClick={() => onDecide('overlap')}>重叠·折中<kbd>V</kbd></button>
              <button title="S：拿不准" className={st.done === 'idk' ? 'on' : ''} onClick={() => onDecide('idk')}>拿不准<kbd>S</kbd></button>
            </div>
          </div>

          <div className="clgroup">
            <div className="clcap">干扰 <span className="muted">可多选，落定前点；评测里分开算</span></div>
            <div className="clbtns cltags">
              <button title="1：污点在分界处" className={st.tags.stain ? 'on' : ''} onClick={() => onToggleTag('stain')}>污点<kbd>1</kbd></button>
              <button title="2：界行或版框压进裁片" className={st.tags.border ? 'on' : ''} onClick={() => onToggleTag('border')}>界行/版框<kbd>2</kbd></button>
              <button title="3：邻字残墨" className={st.tags.residue ? 'on' : ''} onClick={() => onToggleTag('residue')}>邻字残墨<kbd>3</kbd></button>
              <button title="4：其他" className={st.tags.other ? 'on' : ''} onClick={() => onToggleTag('other')}>其他<kbd>4</kbd></button>
            </div>
          </div>

          <div className="clgroup cltools">
            <div className="clcap">工具</div>
            <div className="clbtns">
              <button title="P：折线模式。点空白处加点，点中已有点可拖动，右键删点，Backspace 撤最后一点" className={`clmode${st.mode === 'poly' ? ' on' : ''}`} onClick={onToggleMode}>折线<kbd>P</kbd></button>
              <button title="X：清空折线" onClick={onClearPoly}>清空<kbd>X</kbd></button>
              <button title="U：重开这张卡，改完再落定（后到覆盖）" onClick={onReopen}>重做<kbd>U</kbd></button>
              <span className="muted">{st.mode === 'poly' ? `折线 ${st.poly.length} 点` : ''}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
