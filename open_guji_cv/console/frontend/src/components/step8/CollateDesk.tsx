import { useCallback, useEffect, useState } from 'react'
import { withWorkspace } from '../../api/client'
import { fetchStep8Overview, fetchStep8Pairs } from '../../api/step8'
import type { Step8Overview, Step8Pair, Step8Sample, Step8Tier } from '../../api/step8'

// Step8 · 复核裁决台。设计见 overview 仓 Step8-落库反馈/05。
//
// 与 Step7 定字裁决台的分工（这是本组件存在的理由）：
//   Step7 问「这是什么字」，卡来自 seed_admit 说「我不确定」，是闸；
//   Step8 问「我们和证人谁对」，卡来自对勘说「你跟证人不一样」，**不 block 下一步**。
//
// 三层**不是三个页签，是同一个队列里的三种卡片**——人的判断是连续的：
// 看到 甫→父 会想「这是本书通例」，看到 開→聞 会想「这是认错」，中间不该切页面。
//
// ⭐ 按**字对**聚合，不按条：𠊓→傍 一对就占 24 条，逐条问等于把同一个问题问 24 遍。
// 同一字对的判断几乎总是相同的，所以「N 处一起裁」默认开。

const TIER_ORDER: Step8Tier[] = ['dispute', 'book', 'common', 'taboo']

// 每一层给人的动作不同——这正是分层的用处。
const ACTIONS: Record<Step8Tier, { key: string; label: string; hint?: string }[]> = {
  // ③ 零星分歧：要判谁错。「我方对」不再细分（用户 2026-09-22：「无法区分，不分拆」）
  // ——只看一部证人时，「整理本录错」与「他们底本就是另一个」在证据上长得一模一样。
  dispute: [
    { key: 'ours', label: '我方对', hint: '转写忠于刻本，维持；下轮不再出卡' },
    { key: 'theirs', label: '证人对', hint: '我们认错了，改字并入库' },
    { key: 'unsure', label: '两可', hint: '挂起，下轮还出' },
  ],
  // ② 本书特有：选一个性质即批量确认（用户定的枚举，「名物」拆成人名/物品）
  book: [
    { key: '人名', label: '人名' }, { key: '物品', label: '物品' },
    { key: '通假', label: '通假' }, { key: '避諱', label: '避諱' },
    { key: '正俗', label: '正俗' },
    { key: 'dispute', label: '不是通例，逐条判', hint: '退回 ③' },
  ],
  // ① 通用异体：可推翻。关系图会错——治/冶、輨/轄 两条错边就是被它送进成果档的。
  common: [
    { key: 'ours', label: '确认是异体' },
    { key: 'deny', label: '不是异体·要改', hint: '写进 variants.deny.tsv，任何书都不再当异体' },
    { key: 'unsure', label: '两可' },
  ],
  taboo: [{ key: 'ours', label: '确认是避諱' }],
}

function patchUrl(book: string, s: Step8Sample): string {
  const key = `p${String(s.page).padStart(4, '0')}c${String(s.col).padStart(2, '0')}s${s.slot}${s.sub || ''}`
  return withWorkspace(`/api/cache/${encodeURIComponent(book)}/char_patch/${encodeURIComponent(key)}.png`)
}

function StatTiles({ ov }: { ov: Step8Overview }) {
  const t = ov.tiers
  if (!t) return null
  const agree = ov.n_slots ? ((ov.n_equal || 0) / ov.n_slots * 100).toFixed(1) : '—'
  return (
    <div className="s8-stats">
      <div className="s8-stat"><b>{(ov.n_slots || 0).toLocaleString()}</b><span>字位</span></div>
      <div className="s8-stat"><b>{agree}%</b><span>与证人一致</span></div>
      {TIER_ORDER.map((k) => (
        <div key={k} className={`s8-stat${k === 'dispute' ? ' todo' : ''}`}>
          <b>{t[k]?.pairs ?? 0}</b>
          <span>{ov.tier_label?.[k]}<i>{t[k]?.items ?? 0} 条</i></span>
        </div>
      ))}
    </div>
  )
}

export function CollateDesk({ book }: { book: string }) {
  const [ov, setOv] = useState<Step8Overview | null>(null)
  const [tier, setTier] = useState<Step8Tier | ''>('dispute')
  const [pairs, setPairs] = useState<Step8Pair[]>([])
  const [cur, setCur] = useState(0)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [applyAll, setApplyAll] = useState(true)

  const load = useCallback(async () => {
    if (!book) return
    setBusy(true); setMsg('')
    try {
      const [o, p] = await Promise.all([fetchStep8Overview(book), fetchStep8Pairs(book, tier)])
      setOv(o); setPairs(p.pairs || []); setCur(0)
      if (!o.has_report) setMsg(o.hint || '还没有对勘产物')
    } catch (e) { setMsg(String(e)) } finally { setBusy(false) }
  }, [book, tier])

  useEffect(() => { void load() }, [load])

  const c = pairs[cur]
  const act = c ? ACTIONS[c.tier] : []

  // 裁决落盘还没接（下一步）：先把选择记在前端，避免半成品写脏事件日志。
  const decide = (key: string) => {
    if (!c) return
    setMsg(`（未落盘）${c.pair[0]}→${c.pair[1]} × ${applyAll ? c.n : 1} 处 → ${key}`)
    setCur((i) => Math.min(i + 1, pairs.length - 1))
  }

  return (
    <div className="s8">
      <div className="s8-head">
        <h2>对勘与复核</h2>
        {ov?.built_at && <span className="muted">对勘于 {ov.built_at} · {ov.file}</span>}
        <button onClick={() => void load()} disabled={busy}>{busy ? '读取中…' : '刷新'}</button>
      </div>

      {ov?.has_report && <StatTiles ov={ov} />}

      {!!ov?.absent_runs?.length && (
        <div className="s8-absent">
          <b>证人无此段 {ov.absent_runs.length}</b>
          <span className="muted">校勘按语、卷端题、卷末题之类——证人另有体例、不收。
            不进差异表：拿它们逐字比只会报出一片「改/增删」，而图与转写都没错。</span>
          <ul>{ov.absent_runs.map((a, i) => (
            <li key={i}><b>p{a.page} 第 {a.col} 列</b>，{a.n} 字{a.kind}：<span className="gl">{a.text.slice(0, 60)}{a.text.length > 60 ? '…' : ''}</span></li>
          ))}</ul>
        </div>
      )}

      <div className="s8-filter">
        {TIER_ORDER.map((k) => (
          <button key={k} className={tier === k ? 'on' : ''} onClick={() => setTier(k)}>
            {ov?.tier_label?.[k] || k} {ov?.tiers?.[k]?.pairs ?? 0}
          </button>
        ))}
        <button className={tier === '' ? 'on' : ''} onClick={() => setTier('')}>全部</button>
        <span className="muted">{pairs.length ? `${cur + 1} / ${pairs.length} 对` : '没有待复核的字对'}</span>
      </div>

      {msg && <p className="s8-msg">{msg}</p>}

      {c && (
        <div className="s8-card">
          <div className="s8-imgs">
            {c.samples.map((s) => (
              <img key={s.id} src={patchUrl(book, s)} alt={s.id} title={s.id} />
            ))}
          </div>
          <div className="s8-pair">
            <span className="gl big">{c.pair[0]}</span><span className="arr">→</span>
            <span className="gl big">{c.pair[1]}</span>
            <span className="s8-n">全书 {c.n} 处</span>
            <span className="muted">p{c.pages.slice(0, 6).join('、')}{c.pages.length > 6 ? '…' : ''}</span>
          </div>
          {c.samples.map((s) => (
            <div key={s.id} className="s8-ctx">
              <div><span className="k">我方</span><span className="gl">{s.hyp_ctx}</span></div>
              <div><span className="k">证人</span><span className="gl">{s.ref_ctx}</span></div>
            </div>
          ))}
          <div className="s8-acts">
            {act.map((a) => (
              <button key={a.key} title={a.hint} onClick={() => decide(a.key)}>{a.label}</button>
            ))}
            {c.n > 1 && (
              <label><input type="checkbox" checked={applyAll}
                onChange={(e) => setApplyAll(e.target.checked)} /> {c.n} 处一起裁</label>
            )}
          </div>
          <div className="s8-nav">
            <button onClick={() => setCur((i) => Math.max(0, i - 1))} disabled={cur === 0}>←</button>
            <button onClick={() => setCur((i) => Math.min(pairs.length - 1, i + 1))}
              disabled={cur >= pairs.length - 1}>→</button>
          </div>
        </div>
      )}
    </div>
  )
}
