import { useState } from 'react'
import type { ReviewCard } from '../../types/review'
import { withWorkspace } from '../../api/client'
import type { Group } from './clusterRows'

// 组内按形聚簇、每簇一张代表图（overview #166，2026-09-28）。
// 用户：「图片都显示出来要很久——先聚类，同一类显示一个就行。」后端给了 `clusters`
// 时（借库书缺省开），网格里只画各簇代表图、角上标「×N」；点代表图 = 整簇选/不选，
// 点「×N」展开这一簇的全部成员（这时才加载成员图），成员可以单独点掉。
// 提交时按簇展开成 N 条 confirm 事件，`via: cluster:<簇 id>`（见 `groupRows`）。
// 没有 `clusters`（四庫、北行等，或聚簇关着）就按原样一格一张。

export function ClusterGrid({ g, dropped, onChange }: {
  g: Group
  dropped: Set<string>
  onChange: (next: Set<string>) => void
}) {
  const [open, setOpen] = useState<string | null>(null)

  function toggleIds(ids: string[]) {
    const next = new Set(dropped)
    const anyOn = ids.some((id) => !next.has(id))
    for (const id of ids) { if (anyOn) next.add(id); else next.delete(id) }
    onChange(next)
  }

  if (!g.clusters) {
    return (
      <div className="grp-grid">
        {g.tiles.map((t) => <Tile key={t.id} t={t} off={dropped.has(t.id)} onClick={() => toggleIds([t.id])} />)}
      </div>
    )
  }

  const opened = g.clusters.find((c) => c.id === open)
  return (
    <>
      <div className="grp-grid">
        {g.clusters.map((c, i) => {
          const t = g.tiles[i]
          const ids = c.members.map((m) => m.id)
          const nOn = ids.filter((id) => !dropped.has(id)).length
          return (
            <Tile key={c.id} t={t} off={nOn === 0} partial={nOn > 0 && nOn < ids.length}
                  onClick={() => toggleIds(ids)}
                  badge={c.n > 1 ? (
                    <span className={`grp-count${open === c.id ? ' open' : ''}`}
                          title="点开看这一簇的全部成员，可单独点掉"
                          onClick={(e) => { e.stopPropagation(); setOpen(open === c.id ? null : c.id) }}>
                      {nOn < ids.length ? `${nOn}/${c.n}` : `×${c.n}`}
                    </span>) : null} />
          )
        })}
      </div>
      {opened && (
        <div className="grp-members">
          <div className="muted">
            簇 {opened.id} · {opened.n} 格（点图单独剔掉/加回；与代表图余弦见悬停）
            <button onClick={() => setOpen(null)}>收起</button>
          </div>
          <div className="grp-grid">
            {opened.members.map((m, j) => {
              const off = dropped.has(m.id)
              return (
                <div key={m.id} className={`grp-tile${off ? ' off' : ''}${j === 0 ? ' rep' : ''}`}
                     title={`${m.id}${j === 0 ? ' · 代表图' : ''}${m.sim != null ? ` · cos ${m.sim}` : ''}`}
                     onClick={() => toggleIds([m.id])}>
                  <img src={withWorkspace(m.patch)} alt={m.id} loading="lazy" />
                  <span className="grp-mark">{off ? '✕' : '✓'}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}

function Tile({ t, off, partial, onClick, badge }: {
  t: ReviewCard; off: boolean; partial?: boolean; onClick: () => void; badge?: React.ReactNode
}) {
  const dis = t.first?.agree === false
  return (
    <div className={`grp-tile${off ? ' off' : ''}${partial ? ' partial' : ''}${dis ? ' disagree' : ''}`}
         title={`${t.id}${t.ref?.char ? ` · 整理本 ${t.ref.char}` : ''}`
           + (dis ? ` · 像素 ${t.first?.pixel} / CNN ${t.first?.cnn} 不一致` : '')}
         onClick={onClick}>
      <img src={withWorkspace(t.patch)} alt={t.id} />
      <span className="grp-mark">{off ? '✕' : partial ? '◐' : '✓'}</span>
      {dis && <span className="grp-disagree">≠</span>}
      {badge}
    </div>
  )
}
