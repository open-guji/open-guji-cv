import { useState } from 'react'
import { fetchReviewCardsByCluster, fetchReviewCardsByShape } from '../../api/review'
import { postEvents } from '../../api/events'
import { consumedMsg } from '../../domain'
import type { ReviewShapeGroup } from '../../types/review'
import './groupReview.css'
import { ClusterGrid } from './ClusterGrid'
import { groupCellIds, groupRows } from './clusterRows'

// 按形聚类批审（任务书-C-批审按形聚类分组，2026-09-27）：`group=char` 的进阶
// 版——形近对（今/令、玉/王、大/天……）AI 首选系统性认错方向时，同一个字种组
// 里其实混了两种真实形状，人扫一屏分不清该点掉哪些（Z15 ask 2135）。这里的
// 组已经是"池化＋按形状聚类"拆好的一簇，缺省选中的建议字取整理本对齐字多数
// 票（不是 AI 首选，任务书原话），旁边给另外几个候选，选错了一键切换再整簇
// 提交——跟 GroupReviewPanel 同一条提交路径（POST /api/events），不新造协议。

export function ShapeReviewPanel({ book, pages }: { book: string; pages: string }) {
  const [only, setOnly] = useState<'review' | 'auto' | 'all'>('review')
  const [gate, setGate] = useState(true)
  const [sampleLimit, setSampleLimit] = useState(60)
  // 先纯按形聚类（2026-10-01 用户）：不预设字种，簇只由字块图形状决定，人给每簇一个字。
  const [shapeFirst, setShapeFirst] = useState(false)
  const [thr, setThr] = useState(0.95)
  const [groups, setGroups] = useState<ReviewShapeGroup[]>([])
  const [idx, setIdx] = useState(0)
  const [nTotal, setNTotal] = useState(0)
  const [msg, setMsg] = useState('')
  const [clusterReady, setClusterReady] = useState(true)
  const [dropped, setDropped] = useState<Record<number, Set<string>>>({})
  // 每组当前选中要提交的字——默认建议字，用户可在 candidates 里改选。
  const [picked, setPicked] = useState<Record<number, string>>({})
  const [submitting, setSubmitting] = useState(false)

  const batch = () => `${book}-${pages || 'dev_set'}-decide`

  async function load() {
    setMsg('载入中…')
    try {
      const d = shapeFirst
        ? await fetchReviewCardsByCluster(book, pages || 'dev_set', only, gate, true, sampleLimit, thr)
        : await fetchReviewCardsByShape(book, pages || 'dev_set', only, gate, true, sampleLimit)
      setGroups(d.groups)
      setNTotal(d.n_total)
      setIdx(0)
      setDropped({})
      setPicked({})
      setClusterReady(d.cluster_ready)
      const base = d.groups.length
        ? `${d.groups.length} 簇 · 待审共 ${d.n_total} 格`
          + (d.cluster ? ` · 组内再按形聚成 ${d.cluster.n_clusters} 小簇，每簇一张代表图（余弦 ≥ ${d.cluster.thr}）` : '')
        : '没有待审格'
      setMsg(d.cluster_ready ? base : `${base}（${d.hint || 'embedding 未就绪，按字种分组'}）`)
    } catch (e) {
      setMsg('载入失败：' + (e as Error).message)
    }
  }

  const g = groups[idx]
  const droppedHere = dropped[idx] || new Set<string>()
  const pickedChar = (g && picked[idx]) ?? g?.char ?? null

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

  function pick(ch: string) {
    setPicked((prev) => ({ ...prev, [idx]: ch }))
  }

  function goto(next: number) {
    setIdx(Math.max(0, Math.min(groups.length - 1, next)))
  }

  async function submit() {
    if (!g || !pickedChar) { setMsg('这簇没有可确认的字，去「定字裁决」逐格看'); return }
    const rows = groupRows(g, droppedHere, pickedChar, Date.now())
    if (!rows.length) { setMsg('这簇全点掉了，没有可提交的'); return }
    setSubmitting(true)
    setMsg('提交中…')
    try {
      const r = await postEvents({ batch: batch(), step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
      setMsg(`已写入 ${r.appended ?? rows.length} 条事件（批次 ${batch()}）`
        + consumedMsg(r) + `；跳过 ${groupCellIds(g).length - rows.length} 格`)
      const thisIdx = idx
      const nextGroups = groups.filter((_, i) => i !== thisIdx)
      setGroups(nextGroups)
      const shift = <T,>(rec: Record<number, T>) => {
        const next: Record<number, T> = {}
        for (const [k, v] of Object.entries(rec)) {
          const i = +k
          if (i === thisIdx) continue
          next[i > thisIdx ? i - 1 : i] = v
        }
        return next
      }
      setDropped(shift)
      setPicked(shift)
      setIdx(Math.min(thisIdx, Math.max(0, nextGroups.length - 1)))
    } catch (e) {
      setMsg('提交失败：' + (e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card">
      <h2>按形聚类批审 <span className="muted">形近对（今/令、玉/王…）分开簇，一簇一屏</span></h2>
      <div className="rv-toolbar">
        <label className="muted" title="勾上：不先按整理本字/首选字分池，直接对所有待审格的字块图聚类，一簇标一个字；簇里不对的格点掉。不勾：先按字种分池再拆形近对（旧法）。">
          <input type="checkbox" checked={shapeFirst} onChange={(e) => setShapeFirst(e.target.checked)} /> 先按形聚类（不预设字）
        </label>
        {shapeFirst && (
          <label className="muted" title="簇内两格字块 embedding 的余弦下限。越高簇越纯越碎，越低越省事越容易混进别的字。">
            相似度 ≥ <input value={thr} onChange={(e) => setThr(+e.target.value || 0.95)} size={4} />
          </label>
        )}
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

      {!clusterReady && groups.length > 0 && (
        <div className="grp-warn">⚠ embedding 聚类未就绪，当前按字种分组显示（等同「按字种批审」）。</div>
      )}

      {groups.length > 0 && g && (
        <>
          <div className="grp-nav">
            <button onClick={() => goto(idx - 1)} disabled={idx <= 0}>← 上一簇</button>
            <span className="muted">第 {idx + 1} / {groups.length} 簇 · 全书待审共 {nTotal} 格</span>
            <button onClick={() => goto(idx + 1)} disabled={idx >= groups.length - 1}>下一簇 →</button>
          </div>

          <div className="grp-head">
            <span className="grp-char">{g.char ?? '（未识别）'}</span>
            <span className="muted">
              池 {g.pool}{g.clustered ? '' : '（未聚类）'} · 待审 {g.n} 格
              {g.clusters ? ` · ${g.n_clusters} 小簇${g.truncated ? `（本屏 ${g.clusters.length}）` : ''}`
                : g.truncated ? `（本屏样例 ${g.tiles.length}）` : ''}
              {g.n ? ` · 纯度 ${(g.purity * 100).toFixed(1)}%` : ''}
            </span>
            <span className="muted">
              分布：{g.pages.slice(0, 8).map((p) => `p${p.page}×${p.n}`).join(' ')}
              {g.pages.length > 8 ? ` 等 ${g.pages.length} 页` : ''}
            </span>
          </div>

          {g.candidates.length > 1 && (
            <div className="grp-toolbar">
              <span className="muted">这簇是：</span>
              {g.candidates.map((ch) => (
                <button key={ch} onClick={() => pick(ch)}
                       className={ch === pickedChar ? 'primary' : ''}>
                  {ch}{ch === g.char ? '（建议）' : ''}
                </button>
              ))}
            </div>
          )}
          {(g.ai_majority || g.ref_majority) && (
            <div className="grp-head">
              <span className="muted">
                {g.ai_majority && `AI 首选多数票：${g.ai_majority.char}×${g.ai_majority.n}`}
                {g.ai_majority && g.ref_majority ? ' · ' : ''}
                {g.ref_majority && `整理本对齐多数票：${g.ref_majority.char}×${g.ref_majority.n}`}
              </span>
            </div>
          )}
          {!g.char && (
            <div className="grp-warn">这簇没有任何证据能猜出字（库/上下文/OCR 都没有），去「定字裁决」逐格看。</div>
          )}

          <div className="grp-toolbar">
            <button onClick={selectAll}>全选</button>
            <button onClick={selectNone}>全不选</button>
            <button onClick={submit} disabled={submitting || !pickedChar}>
              提交为「{pickedChar ?? '？'}」（{groupCellIds(g).length - droppedHere.size} / {groupCellIds(g).length} 格）
            </button>
          </div>

          <ClusterGrid key={idx} g={g} dropped={droppedHere} onChange={setHere} />
        </>
      )}
    </div>
  )
}
