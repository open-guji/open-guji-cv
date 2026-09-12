import type { CutlineCase } from '../../types/cutline'

// Step7「切分裁决」板块专用卡片（overview 2026-09-11 下发）。
//
// 与 Step3 的 `CutlineCard` 故意不共用：那边是给「拖切线、攒 touching-cuts
// 金标」用的全量标注工具，这里只是「算法给了几种切法，选一个」——不需要
// 拖直线/画折线、不需要"缝正确"/"重叠·折中"/干扰标签这些跟"选哪个"无关
// 的操作。核心判据也不同：这里每个候选旁边直接摆 Step5 库匹配认出的字，
// 跟整理本期望字一比对，人一眼就能判断"选这条，两边都能认对"。

const CL_KIND: Record<string, string> = { straight: '直线', seam_narrow: '窄走廊', seam_wide: '宽走廊' }

interface Props {
  idx: number
  c: CutlineCase
  pick: number | null           // 当前选中的候选下标；null = 还没选
  done?: string                 // 'confirmed' | 'idk' | undefined
  isCurrent: boolean
  onFocus: () => void
  onPick: (k: number) => void
  onConfirm: () => void
  onIdk: () => void
  onReopen: () => void
}

function matchLabel(m: { char: string | null; cov: number } | null | undefined, expect?: string) {
  if (!m) return <span className="muted">无识别</span>
  const hit = !!(expect && m.char === expect)
  return (
    <span className={hit ? 'clm-hit' : ''}>
      {m.char || '？'} <span className="muted">{(m.cov * 100).toFixed(0)}%</span>
    </span>
  )
}

export function BlockingCutlineCard({ idx, c, pick, done, isCurrent, onFocus, onPick, onConfirm, onIdk, onReopen }: Props) {
  const cands = c.candidates || []
  const h = c.crop_y1 - c.crop_y0
  const w = c.col_w || (c.x1 - c.x0 + 12)
  const scale = Math.min(2, Math.max(1, Math.floor((100 * 300) / w) / 100))

  return (
    <div id={`bcc${idx}`} className={`clcard${isCurrent ? ' cur' : ''}`} data-done={done || ''}
         onClick={onFocus}>
      <div className="clhead"><b>{c.id}</b><span className="muted">p{c.page} 列{c.col} 格线{c.bi}</span></div>
      <div className="clbody">
        <div className="climg" style={{ height: h * scale, width: w * scale }}>
          <img src={c.img} height={h * scale} alt={c.id} loading="lazy" style={{ width: 'auto', height: h * scale }} />
          {cands.map((cd, k) => {
            if (!cd.y || !cd.y.length) return null
            const cls = cd.kind === 'seam_wide' ? 'wide' : 'narrow'
            return (
              <svg key={k} className="clsvg" style={{ height: h * scale }}>
                <polyline className={`clcand ${cls}${k === pick ? ' clcand-pick' : ''}`}
                          points={cd.y.map((yy, j) => `${(c.x0 + j) * scale},${(yy - c.crop_y0) * scale}`).join(' ')} />
              </svg>
            )
          })}
          {(!cands[pick ?? -1]?.y) && (
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
                <tr key={k} className={k === pick ? 'on' : ''} onClick={() => onPick(k)}>
                  <td className="bcc-kind">{CL_KIND[cd.kind] || cd.kind}{k === c.chosen ? ' ·现役' : ''}</td>
                  <td>{matchLabel(cd.match_above, c.char_above)}</td>
                  <td>{matchLabel(cd.match_below, c.char_below)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="clbtns">
            <button className={done === 'confirmed' ? 'on' : ''} disabled={pick == null}
                    onClick={onConfirm}>落定选中的切法</button>
            <button className={done === 'idk' ? 'on' : ''} onClick={onIdk}>拿不准</button>
            {done && <button onClick={onReopen}>重做</button>}
          </div>
        </div>
      </div>
    </div>
  )
}
