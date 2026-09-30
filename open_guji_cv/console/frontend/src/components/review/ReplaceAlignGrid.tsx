import type { ReviewCard } from '../../types/review'
import { withWorkspace } from '../../api/client'
import type { GridState } from './reviewClass'
import './groupReview.css'

// 对齐改字层 · 网格（overview#265）：一屏几十张缩略图，每张下面标整理本字，缺省「采信整理本」。
// 人只点掉异常的：点一下 → 字形不完整，再点 → 跳过，再点回到采信。状态与提交在 ReviewPanel
// （`gridRows` 出事件行，与逐张裁决逐字段相同）；这里只画。交互参照印章遮挡的「整组确认」。

const MARK: Record<GridState, string> = { accept: '✓', truncated: '缺', skip: '跳' }
const TITLE: Record<GridState, string> = { accept: '采信整理本', truncated: '字形不完整', skip: '跳过' }

export function ReplaceAlignGrid({ cards, states, onToggle }: {
  cards: ReviewCard[]
  states: Record<string, GridState | undefined>
  onToggle: (id: string) => void
}) {
  return (
    <div className="grp-grid ra-grid" data-testid="ra-grid">
      {cards.map((c) => {
        const s = states[c.id] ?? 'accept'
        return (
          <div key={c.id} className={`grp-tile ra-tile ra-${s}${c.shadow?.pre ? ' ra-pre' : ''}`} data-id={c.id} data-state={s}
               title={`${c.id} · 整理本「${c.ref?.char ?? ''}」· 现：${TITLE[s]}（点一下换档）`
                 + (c.shadow ? ` · 影子「${c.shadow.char}」${c.shadow.conf.toFixed(2)}${c.shadow.pre ? '（预勾）' : ''}` : '')}
               onClick={() => onToggle(c.id)}>
            <img src={withWorkspace(c.patch)} alt={c.id} loading="lazy" />
            <span className="grp-mark">{MARK[s]}</span>
            <div className="ra-ref">{c.ref?.char ?? '？'}</div>
            {c.shadow && (
              <span className="ra-shadow" data-testid="ra-shadow">影子 {c.shadow.conf.toFixed(2)}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
