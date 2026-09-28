import { useState } from 'react'
import { fetchReviewCardsGrouped } from '../../api/review'
import { postEvents } from '../../api/events'
import { consumedMsg } from '../../domain'
import type { ReviewCardGroup } from '../../types/review'
import './groupReview.css'
import { ClusterGrid } from './ClusterGrid'
import { groupCellIds, groupRows } from './clusterRows'

// 按字种批审（任务书-C-待审卡按字种批审，2026-09-27）：一个字种一屏，图块
// 网格显示，缺省全选，点掉不对的再一键提交——积累本书字形最高效的办法。
// 提交走既有的 `POST /api/events`（跟「定字裁决」逐格一条 confirm 事件，
// 一字不改协议），校对者 id 由后端 `require_reviewer` 认出来，不必在这里传。
// 被点掉的格什么也不做：不提交就还是待审格，下次载入（这里或「定字裁决」）
// 照样出来，也就是"退回逐格审查"。
// 「定为」框（用户 09-28：整组都认错了字时只能全不选）：缺省是组的首选字，
// 可改成别的字，或一键用整理本对齐字；提交的 confirm 事件 shape 就是这个字，
// 跟「定字裁决」逐格改字后提交同一协议。

export function GroupReviewPanel({ book, pages }: { book: string; pages: string }) {
  const [only, setOnly] = useState<'review' | 'auto' | 'all'>('review')
  const [gate, setGate] = useState(true)
  const [sampleLimit, setSampleLimit] = useState(60)
  const [groups, setGroups] = useState<ReviewCardGroup[]>([])
  const [idx, setIdx] = useState(0)
  const [nTotal, setNTotal] = useState(0)
  const [msg, setMsg] = useState('')
  // 组内被点掉（退回逐格审查）的格 id，按组下标存——切组不丢，重新载入才清。
  const [dropped, setDropped] = useState<Record<number, Set<string>>>({})
  const [submitting, setSubmitting] = useState(false)
  // 组内「定为」的字，按组下标存；没改过就用组的首选字。
  const [override, setOverride] = useState<Record<number, string>>({})

  const batch = () => `${book}-${pages || 'dev_set'}-decide`

  async function load() {
    setMsg('载入中…')
    try {
      const d = await fetchReviewCardsGrouped(book, pages || 'dev_set', only, gate, true, sampleLimit)
      setGroups(d.groups)
      setNTotal(d.n_total)
      setIdx(0)
      setDropped({})
      setOverride({})
      setMsg(d.groups.length
        ? `${d.groups.length} 个字种 · 待审共 ${d.n_total} 格`
          + (d.cluster ? ` · 按形聚成 ${d.cluster.n_clusters} 簇，每簇一张代表图（余弦 ≥ ${d.cluster.thr}）` : '')
        : '没有待审格')
    } catch (e) {
      setMsg('载入失败：' + (e as Error).message)
    }
  }

  const g = groups[idx]
  const droppedHere = dropped[idx] || new Set<string>()
  const shape = (override[idx] ?? g?.char ?? '').trim()
  const changed = !!g && shape !== (g.char ?? '')

  function setShape(v: string) {
    setOverride((prev) => ({ ...prev, [idx]: v }))
  }

  function setHere(next: Set<string>) {
    setDropped((prev) => ({ ...prev, [idx]: next }))
  }

  function selectAll() {
    setDropped((prev) => ({ ...prev, [idx]: new Set() }))
  }

  function selectNone() {
    if (!g) return
    setDropped((prev) => ({ ...prev, [idx]: new Set(groupCellIds(g)) }))
  }

  function goto(next: number) {
    setIdx(Math.max(0, Math.min(groups.length - 1, next)))
  }

  async function submit() {
    if (!g) return
    if (!shape) { setMsg('「定为」是空的：填上这组的正确字再提交，或去「定字裁决」逐格看'); return }
    if ([...shape].length !== 1) { setMsg(`「定为」只填一个字（现在是「${shape}」）`); return }
    const rows = groupRows(g, droppedHere, shape, Date.now())
    if (!rows.length) { setMsg('这组全点掉了，没有可提交的'); return }
    setSubmitting(true)
    setMsg('提交中…')
    try {
      const r = await postEvents({ batch: batch(), step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
      setMsg(`已写入 ${r.appended ?? rows.length} 条事件，定为「${shape}」（批次 ${batch()}）`
        + consumedMsg(r) + `；跳过 ${groupCellIds(g).length - rows.length} 格`)
      // 这一组处理完了：从列表里摘掉，其余组下标随之前移，不必手动翻页。
      const thisIdx = idx
      const nextGroups = groups.filter((_, i) => i !== thisIdx)
      setGroups(nextGroups)
      const shift = <T,>(prev: Record<number, T>) => {
        const next: Record<number, T> = {}
        for (const [k, v] of Object.entries(prev)) {
          const i = +k
          if (i === thisIdx) continue
          next[i > thisIdx ? i - 1 : i] = v
        }
        return next
      }
      setDropped(shift)
      setOverride(shift)
      setIdx(Math.min(thisIdx, Math.max(0, nextGroups.length - 1)))
    } catch (e) {
      setMsg('提交失败：' + (e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card">
      <h2>按字种批审 <span className="muted">一个字种一屏，多格一起确认，积累本书字形</span></h2>
      <div className="rv-toolbar">
        <label className="muted">范围
          <select value={only} onChange={(e) => setOnly(e.target.value as typeof only)}>
            <option value="review">只看待审</option>
            <option value="auto">抽查自动档</option>
            <option value="all">全部</option>
          </select>
        </label>
        <label className="muted" title="每组最多显示多少张样例图（组的真实待审数见 n，不受这个限制）">
          样例上限 <input value={sampleLimit} onChange={(e) => setSampleLimit(+e.target.value || 60)} size={4} />
        </label>
        <label className="muted" title="顺序闸：字位旁边那条切分线还没 review 时先不出卡">
          <input type="checkbox" checked={gate} onChange={(e) => setGate(e.target.checked)} /> 先切线后字符
        </label>
        <button onClick={load}>载入</button>
        <span className="muted">{msg}</span>
      </div>

      {groups.length > 0 && g && (
        <>
          <div className="grp-nav">
            <button onClick={() => goto(idx - 1)} disabled={idx <= 0}>← 上一组</button>
            <span className="muted">第 {idx + 1} / {groups.length} 组 · 全书待审共 {nTotal} 格</span>
            <button onClick={() => goto(idx + 1)} disabled={idx >= groups.length - 1}>下一组 →</button>
          </div>

          <div className="grp-head">
            <span className="grp-char">{g.char ?? '（未识别）'}</span>
            <span className="muted">待审 {g.n} 格
              {g.clusters ? ` · ${g.n_clusters} 簇${g.truncated ? `（本屏 ${g.clusters.length} 簇）` : ''}`
                : g.truncated ? `（本屏样例 ${g.tiles.length}）` : ''}</span>
            <span className="muted">
              分布：{g.pages.slice(0, 8).map((p) => `p${p.page}×${p.n}`).join(' ')}
              {g.pages.length > 8 ? ` 等 ${g.pages.length} 页` : ''}
            </span>
          </div>
          {g.ref_char && (
            <div className="grp-warn">
              ⚠ 首选字与整理本对齐字不同（整理本作「{g.ref_char}」）——这组格已与同字种的组分开，
              批量确认前建议逐张看清楚。
            </div>
          )}
          {!g.char && (
            <div className="grp-warn">这组没有任何证据能猜出字（库/上下文/OCR 都没有）：在「定为」里填上正确字再提交，或去「定字裁决」逐格看。</div>
          )}

          <div className="grp-toolbar">
            <button onClick={selectAll}>全选</button>
            <button onClick={selectNone}>全不选</button>
            <label className="muted" title="选中的格一律定为这个字；整组都认错了就在这里改成正确字">
              定为 <input className={'grp-shape' + (changed ? ' changed' : '')} value={override[idx] ?? g.char ?? ''}
                onChange={(e) => setShape(e.target.value)} size={2} />
            </label>
            {g.ref_char && shape !== g.ref_char && (
              <button onClick={() => setShape(g.ref_char!)}>用整理本「{g.ref_char}」</button>
            )}
            {changed && g.char && <button onClick={() => setShape(g.char!)}>还原「{g.char}」</button>}
            <button onClick={submit} disabled={submitting || !shape}>
              提交{shape ? `为「${shape}」` : ''}（{groupCellIds(g).length - droppedHere.size} / {groupCellIds(g).length} 格）
            </button>
          </div>

          <ClusterGrid key={idx} g={g} dropped={droppedHere} onChange={setHere} />
        </>
      )}
    </div>
  )
}
