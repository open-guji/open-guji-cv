import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { withWorkspace } from '../../api/client'
import { fetchStep8Overview, fetchStep8Queue, postStep8Decide, postStep8Seg } from '../../api/step8'
import type { Step8Bucket, Step8Cat, Step8Group, Step8Overview, Step8Queue, Step8Sample, Step8Seg } from '../../api/step8'

// Step8 · 复核裁决台。设计见 overview 仓 Step8-落库反馈/05。
//
// 与 Step7 定字裁决台的分工（这是本组件存在的理由）：
//   Step7 问「这是什么字」，卡来自 seed_admit 说「我不确定」，是闸；
//   Step8 问「我们和校对本谁对」，卡来自对勘说「你跟校对本不一样」，**不 block 下一步**。
//
// 两层分类（用户 2026-09-24）：
//   第一层  待审 · 我方对 · 校对本对 · 都不对
//   第二层  （只挂在「我方对」下）异体字 · 通假字 · 避讳字 · 其他
// 之前页签是自动判据的五档（零星分歧 / 本书特有 / 异体 / 通假 / 避諱），把「机器为什么
// 归不了」当成了分类。现在自动判据只作预标注，卡片上选哪一类就**挪进**哪一类，各类之间
// 随时能再挪、也能退回待审。后端怎么记见 feedback/collate_state.py。
//
// ⭐ 按**字对**聚合，不按条：𠊓→傍 一对就占 24 条，逐条问等于把同一个问题问 24 遍。

const BUCKETS: { key: Step8Bucket; label: string }[] = [
  { key: 'pending', label: '待审' },
  { key: 'ours', label: '我方对' },
  { key: 'theirs', label: '校对本对' },
  { key: 'neither', label: '都不对' },
]
const WHO: { key: Exclude<Step8Bucket, 'pending'>; label: string; hint: string }[] = [
  { key: 'ours', label: '我方对', hint: '转写忠于刻本，这一格保持我方的字' },
  { key: 'theirs', label: '校对本对', hint: '我们认错了：这一格改成校对本的字并入库' },
  { key: 'neither', label: '都不对', hint: '两边都错：输入正确的字' },
]
const CATS: { key: Step8Cat; label: string; hint: string }[] = [
  { key: 'variant', label: '异体字', hint: '同一个字的不同写法' },
  { key: 'jiajie', label: '通假字', hint: '本字不在、借另一个字代替' },
  { key: 'taboo', label: '避讳字', hint: '为避当朝讳而改字' },
  { key: 'other', label: '其他', hint: '不同字，非上述三类' },
]
const CAT_LABEL = Object.fromEntries(CATS.map((c) => [c.key, c.label])) as Record<Step8Cat, string>
const BUCKET_LABEL = Object.fromEntries(BUCKETS.map((b) => [b.key, b.label])) as Record<Step8Bucket, string>
const TIER_HINT: Record<string, string> = {
  taboo: '避諱表', variant: '异体关系图', jiajie: '通假表', book: '本书反复出现', dispute: '零星分歧',
}
// 图右边的切分反馈复选框（用户 2026-09-24）：与分类独立，勾了不影响谁对/哪一类，
// 只写一条 seg_defect 留给 Step3 的打回台账
const SEG: { key: Step8Seg; label: string }[] = [
  { key: 'truncated', label: '字形不完整' },
  { key: 'contaminated', label: '有噪声' },
]
const MAX_IMGS = 12
const MAX_CTX = 4

type Sel = { who: Exclude<Step8Bucket, 'pending'>; cat: Step8Cat; fix: string }

// 卡片默认选中：待审卡按预标注选「我方对 · X」；已归类的卡选中它现在所在的那一类
function selOf(g: Step8Group): Sel {
  if (g.who === 'pending') return { who: 'ours', cat: g.default_cat, fix: '' }
  return { who: g.who, cat: g.cat || g.default_cat, fix: g.fix }
}

function sameAsCard(g: Step8Group, s: Sel): boolean {
  if (g.who === 'pending' || g.basis !== 'human') return false   // 自动归的，回车 = 人确认一次
  if (g.who !== s.who) return false
  if (s.who === 'ours') return g.cat === s.cat
  if (s.who === 'neither') return g.fix === s.fix.trim()
  return true
}

function describe(s: { who: Step8Bucket | ''; cat?: Step8Cat | null; fix?: string }): string {
  if (!s.who || s.who === 'pending') return '待审'
  if (s.who === 'ours') return `我方对 · ${CAT_LABEL[s.cat || 'other']}`
  if (s.who === 'neither') return `都不对（${s.fix}）`
  return BUCKET_LABEL[s.who]
}

// 字位坐标：第几页、第几列、第几个字（a/b = 夹注右行/左行）
function loc(s: Step8Sample): string {
  if (s.page == null) return s.id
  return `p${s.page} 第${s.col}列第${s.slot}字${s.sub ? `（夹注${s.sub === 'a' ? '右' : '左'}）` : ''}`
}

function patchUrl(book: string, s: Step8Sample): string {
  const key = `p${String(s.page).padStart(4, '0')}c${String(s.col).padStart(2, '0')}s${s.slot}${s.sub || ''}`
  return withWorkspace(`/api/cache/${encodeURIComponent(book)}/char_patch/${encodeURIComponent(key)}.png`)
}

function StatTiles({ ov }: { ov: Step8Overview }) {
  const agree = ov.n_slots ? ((ov.n_equal || 0) / ov.n_slots * 100).toFixed(1) : '—'
  return (
    <div className="s8-stats">
      <div className="s8-stat"><b>{(ov.n_slots || 0).toLocaleString()}</b><span>字位</span></div>
      <div className="s8-stat"><b>{agree}%</b><span>与校对本一致</span></div>
      {!!ov.gaps && <div className="s8-stat"><b>{ov.gaps}</b><span>增删（不聚合，不在下面的队列里）</span></div>}
    </div>
  )
}

function Tab({ on, label, c, onClick }: {
  on: boolean; label: string; c?: { pairs: number; items: number; auto: number }; onClick: () => void
}) {
  return (
    <button className={on ? 'on' : ''} onClick={onClick}
      title={c ? `${c.pairs} 对 · ${c.items} 处${c.auto ? `（其中 ${c.auto} 对是自动归的，未人裁）` : ''}` : ''}>
      {label} <b>{c?.pairs ?? 0}</b>
      {c && <i>{c.items} 处{c.auto ? ` · 自动 ${c.auto}` : ''}</i>}
    </button>
  )
}

type Undo = { pair: [string, string]; ids: string[]; to: string; prev: { who: Step8Bucket | ''; cat: Step8Cat | null; fix: string } }

export function CollateDesk({ book }: { book: string }) {
  const [ov, setOv] = useState<Step8Overview | null>(null)
  const [bucket, setBucket] = useState<Step8Bucket>('pending')
  const [cat, setCat] = useState<Step8Cat | ''>('')           // 我方对下的小类；空 = 全部
  const [q, setQ] = useState<Step8Queue | null>(null)
  const [cur, setCur] = useState(0)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [undo, setUndo] = useState<Undo | null>(null)
  // 切分反馈的本地覆盖：点了立刻显示，不等重载队列
  const [seg, setSeg] = useState<Record<string, Step8Seg[]>>({})
  // 「N 处一起裁」：勾上一次挪全部；不勾**只挪当前这一处**，剩下的留在原类
  const [applyAll, setApplyAll] = useState(true)
  const [at, setAt] = useState(0)
  const [sel, setSel] = useState<Sel>({ who: 'ours', cat: 'other', fix: '' })
  // 提交后重载队列时要停在哪张卡：记一个字位 id，重载后找含它的那组
  const focusId = useRef<string | null>(null)

  const groups = useMemo(() => q?.groups || [], [q])
  const c: Step8Group | undefined = groups[cur]

  const loadQueue = useCallback(async () => {
    if (!book) return
    setBusy(true)
    try {
      const r = await fetchStep8Queue(book, bucket, bucket === 'ours' ? cat : '')
      setQ(r)
      const f = focusId.current
      focusId.current = null
      const gs = r.groups || []
      const i = f ? gs.findIndex((g) => g.ids.includes(f)) : -1
      setCur((old) => (i >= 0 ? i : Math.max(0, Math.min(f ? old : 0, gs.length - 1))))
      setAt(0)
    } catch (e) { setMsg(String(e)) } finally { setBusy(false) }
  }, [book, bucket, cat])

  const loadAll = useCallback(async () => {
    if (!book) return
    setMsg('')
    try {
      const o = await fetchStep8Overview(book)
      setOv(o)
      if (!o.has_report) setMsg(o.hint || '还没有对勘产物')
    } catch (e) { setMsg(String(e)) }
    await loadQueue()
  }, [book, loadQueue])

  useEffect(() => { void loadAll() }, [book])          // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { void loadQueue() }, [bucket, cat]) // eslint-disable-line react-hooks/exhaustive-deps

  // 换卡就把选中态重置成这张卡的默认
  useEffect(() => { if (c) setSel(selOf(c)) }, [c])

  const go = useCallback((d: number) => {
    setAt(0)
    setCur((i) => Math.max(0, Math.min(groups.length - 1, i + d)))
  }, [groups.length])

  // 把当前卡（或其中一处）挪进 `to`。`to.who` 空 = 退回待审。
  const move = useCallback(async (to: { who: Step8Bucket | ''; cat?: Step8Cat; fix?: string }) => {
    if (!c || busy) return
    if (to.who === 'neither' && !(to.fix || '').trim()) { setMsg('「都不对」要先输入正确的字'); return }
    const ids = applyAll ? c.ids : [c.ids[at]]
    // 挪完停在哪：一起裁 → 下一张卡；只裁一处 → 同一字对剩下的那几处
    const rest = c.ids.filter((x) => !ids.includes(x))
    focusId.current = rest[0] ?? groups[cur + 1]?.ids[0] ?? null
    setBusy(true)
    try {
      const r = await postStep8Decide({
        book, pair: c.pair, ids, who: to.who,
        cat: to.who === 'ours' ? to.cat : undefined,
        fix: to.who === 'neither' ? (to.fix || '').trim() : undefined,
      })
      if (!r.ok) { setMsg(r.error || '提交失败'); focusId.current = null; return }
      const toLabel = describe({ who: to.who, cat: to.cat, fix: (to.fix || '').trim() })
      setUndo({ pair: c.pair, ids, to: toLabel,
        prev: { who: c.basis === 'human' ? c.who : '', cat: c.cat, fix: c.fix } })
      setMsg(`${c.pair[0]}→${c.pair[1]} × ${ids.length} 处 → ${toLabel}`
        + `${r.changed ? `；${r.changed} 处改字为「${r.final}」` : ''}`
        + `${r.consume_error ? '；⚠ 消费失败 ' + r.consume_error : ''}`)
    } catch (e) { setMsg(String(e)); focusId.current = null } finally { setBusy(false) }
    await loadQueue()
  }, [c, busy, applyAll, at, groups, cur, book, loadQueue])

  const doUndo = useCallback(async () => {
    if (!undo || busy) return
    const p = undo.prev
    setBusy(true)
    try {
      const r = await postStep8Decide({
        book, pair: undo.pair, ids: undo.ids, who: p.who === 'pending' ? '' : p.who,
        cat: p.who === 'ours' ? (p.cat || 'other') : undefined,
        fix: p.who === 'neither' ? p.fix : undefined,
      })
      setMsg(r.ok ? `已撤销：${undo.pair[0]}→${undo.pair[1]} × ${undo.ids.length} 处退回${describe(p)}` : (r.error || '撤销失败'))
      setUndo(null)
      focusId.current = undo.ids[0]
    } catch (e) { setMsg(String(e)) } finally { setBusy(false) }
    await loadQueue()
  }, [undo, busy, book, loadQueue])

  // ↵ / 「确认」：确认当前选中并下一张。选中的就是它现在所在的类（且已是人裁）→ 只翻页。
  // ← / → 只翻页、不提交（用户 2026-09-24：确认与翻页分开）。
  const confirmNext = useCallback(async () => {
    if (!c || busy) return
    if (sameAsCard(c, sel)) {
      if (!applyAll && at + 1 < c.n) setAt(at + 1); else go(1)
      return
    }
    // 「都不对」还没填字：只翻页，不写一条空字的裁决
    if (sel.who === 'neither' && !sel.fix.trim()) { go(1); return }
    await move(sel)
  }, [c, busy, sel, applyAll, at, go, move])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      if (e.key === 'Enter') { e.preventDefault(); void confirmNext() }
      else if (e.key === 'ArrowRight') { e.preventDefault(); go(1) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirmNext, go])

  const segOf = useCallback((s: Step8Sample) => seg[s.id] ?? s.seg ?? [], [seg])

  // 勾/取消一项。`ss` 是这次作用的那几处：一起裁 = 这张卡全部，否则只当前那一处。
  // 一起裁时「勾着」= 每处都勾了；点一下 = 全部勾上（或全部取消），各处另一项不动。
  const toggleSeg = useCallback(async (ss: Step8Sample[], f: Step8Seg) => {
    const was = Object.fromEntries(ss.map((s) => [s.id, segOf(s)]))
    const allOn = ss.every((s) => was[s.id].includes(f))
    const now = Object.fromEntries(ss.map((s) => [s.id,
      allOn ? was[s.id].filter((x) => x !== f)
        : was[s.id].includes(f) ? was[s.id] : [...was[s.id], f]]))
    setSeg((m) => ({ ...m, ...now }))
    try {
      const r = await postStep8Seg(book, ss.map((s) => ({ id: s.id, flags: now[s.id] })))
      if (!r.ok) { setSeg((m) => ({ ...m, ...was })); setMsg(r.error || '切分反馈没存上') }
      else if (r.consume_error) setMsg('切分反馈已记下；⚠ 消费失败 ' + r.consume_error)
    } catch (e) { setSeg((m) => ({ ...m, ...was })); setMsg(String(e)) }
  }, [segOf, book])

  const segBoxes = (ss: Step8Sample[]) => (
    <div className="s8-seg">
      {SEG.map((f) => {
        const n = ss.filter((s) => segOf(s).includes(f.key)).length
        return (
          <label key={f.key} className={n ? 'on' : ''}
            title={ss.length > 1 ? `作用于这 ${ss.length} 处${n && n < ss.length ? `（现在 ${n} 处勾了）` : ''}` : ''}>
            <input type="checkbox" checked={n === ss.length}
              ref={(el) => { if (el) el.indeterminate = n > 0 && n < ss.length }}
              onChange={() => void toggleSeg(ss, f.key)} />{f.label}
          </label>
        )
      })}
    </div>
  )

  const counts = q?.counts
  const shown = c ? (applyAll ? c.samples : c.samples.slice(at, at + 1)) : []

  return (
    <div className="s8">
      <div className="s8-head">
        <h2>对勘与复核</h2>
        {ov?.built_at && <span className="muted">对勘于 {ov.built_at} · {ov.file}</span>}
        <button onClick={() => void loadAll()} disabled={busy}>{busy ? '读取中…' : '刷新'}</button>
      </div>

      {ov?.has_report && <StatTiles ov={ov} />}

      {!!ov?.absent_runs?.length && (
        <details className="s8-absent">
          <summary><b>校对本无此段 {ov.absent_runs.length}</b>
            <span className="muted">校勘按语、卷端题、卷末题之类——校对本另有体例、不收，不进差异表。</span></summary>
          <ul>{ov.absent_runs.map((a, i) => (
            <li key={i}><b>p{a.page} 第 {a.col} 列</b>，{a.n} 字{a.kind}：<span className="gl">{a.text.slice(0, 60)}{a.text.length > 60 ? '…' : ''}</span></li>
          ))}</ul>
        </details>
      )}

      <div className="s8-filter">
        {BUCKETS.map((b) => (
          <Tab key={b.key} on={bucket === b.key} label={b.label} c={counts?.[b.key]}
            onClick={() => { setBucket(b.key); setCat('') }} />
        ))}
      </div>
      {bucket === 'ours' && (
        <div className="s8-filter s8-sub">
          <Tab on={cat === ''} label="全部" c={counts?.ours} onClick={() => setCat('')} />
          {CATS.map((k) => (
            <Tab key={k.key} on={cat === k.key} label={k.label} c={counts?.cats?.[k.key]}
              onClick={() => setCat(k.key)} />
          ))}
        </div>
      )}
      <p className="s8-msg">
        {groups.length ? `${cur + 1} / ${groups.length} 对` : '这一类是空的'}
        {q?.truncated ? `（只列前 ${groups.length} 对，共 ${q.total}）` : ''}
        {msg && <> · {msg}</>}
        {undo && <button className="s8-undo" onClick={() => void doUndo()} disabled={busy}>撤销</button>}
      </p>

      {c && (
        <div className="s8-card">
          <div className="s8-imgs">
            {shown.slice(0, MAX_IMGS).map((s) => (
              <img key={s.id} src={patchUrl(book, s)} alt={s.id} title={`${loc(s)}  ${s.id}`} />
            ))}
            {shown.length > MAX_IMGS && <span className="muted">另 {shown.length - MAX_IMGS} 处</span>}
          </div>
          <div className="s8-pair">
            <span className="gl big">{c.pair[0]}</span><span className="arr">→</span>
            <span className="gl big">{c.pair[1]}</span>
            <span className="s8-n">全书 {c.n} 处{!applyAll && c.n > 1 ? ` · 正在裁第 ${at + 1} 处` : ''}</span>
            <span className={`s8-badge ${c.basis || 'pending'}`}>
              {c.basis === 'auto' ? `自动：${TIER_HINT[c.tier] || c.tier}`
                : c.basis === 'convention' ? '本书通例（旧裁）'
                : c.basis === 'human' ? `人裁 ${c.decided_at.slice(0, 16).replace('T', ' ')}`
                : `预标注：${TIER_HINT[c.tier] || c.tier}`}
            </span>
            {c.who !== 'pending' && <span className="s8-final">定字「{c.final}」</span>}
          </div>
          <div className="s8-locs">
            {c.samples.map((s, i) => (
              <span key={s.id} className={!applyAll && i === at ? 'cur' : ''}>{loc(s)}</span>
            ))}
          </div>
          {shown.slice(0, MAX_CTX).map((s) => (
            <div key={s.id} className="s8-ctx">
              <div className="s8-loc">{loc(s)}</div>
              <div><span className="k">我方</span><span className="gl">{s.hyp_ctx}</span></div>
              <div><span className="k">校对本</span><span className="gl">{s.ref_ctx}</span></div>
            </div>
          ))}
          {shown.length > MAX_CTX && <p className="s8-hint">另 {shown.length - MAX_CTX} 处上下文未展开</p>}

          <div className="s8-acts">
            {WHO.map((a) => (
              <button key={a.key} title={a.hint} className={sel.who === a.key ? 'on' : ''}
                onClick={() => {
                  // 校对本对是终态，点了就挪；我方对 / 都不对 还要再选小类 / 填字
                  if (a.key === 'theirs') void move({ who: 'theirs' })
                  else setSel((s) => ({ ...s, who: a.key }))
                }}>{a.label}</button>
            ))}
            {/* 切分反馈挨着「都不对」（用户 2026-09-24）：作用于当前显示的那几处——
                一起裁 = 全部 N 处，不勾一起裁 = 正在裁的那一处，于是分开裁时也能分开标 */}
            {segBoxes(shown)}
            {c.n > 1 && (
              <label><input type="checkbox" checked={applyAll}
                onChange={(e) => { setApplyAll(e.target.checked); setAt(0) }} /> {c.n} 处一起裁</label>
            )}
          </div>
          {sel.who === 'ours' && (
            <div className="s8-acts">
              <span className="k">这一对是</span>
              {CATS.map((r) => (
                <button key={r.key} title={r.hint} className={sel.cat === r.key ? 'on' : ''}
                  onClick={() => void move({ who: 'ours', cat: r.key })}>{r.label}</button>
              ))}
            </div>
          )}
          {sel.who === 'neither' && (
            <div className="s8-acts">
              <span className="k">正确的字</span>
              <input className="s8-fix" value={sel.fix} maxLength={2} placeholder="输入" autoFocus
                onChange={(e) => setSel((s) => ({ ...s, fix: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); void move({ who: 'neither', fix: sel.fix }) }
                  else if (e.key === 'Escape') { (e.target as HTMLInputElement).blur() }
                }} />
              <button disabled={!sel.fix.trim()} onClick={() => void move({ who: 'neither', fix: sel.fix })}>确认</button>
            </div>
          )}
          <div className="s8-nav">
            <button onClick={() => go(-1)} disabled={cur === 0} title="上一对（不提交）">←</button>
            <button onClick={() => go(1)} disabled={cur >= groups.length - 1} title="下一对（不提交）">→</button>
            <button className="s8-ok" onClick={() => void confirmNext()} disabled={busy}
              title={`按当前选中（${describe(sel)}）确认并下一对`}>确认</button>
            {/* 说明挪到最右、小字，不占左边的注意力 */}
            <span className="s8-navhint">
              点类别即挪入该类<br />
              ↵ / 确认：按当前选中（{describe(sel)}）确认并下一对<br />
              ← → 翻页，不提交
            </span>
            {c.who !== 'pending' && (
              <button className="s8-back" disabled={busy || c.basis !== 'human'}
                title={c.basis === 'human' ? '撤掉人裁，这几处回到待审' : '这张是自动归的，本来就没人裁过'}
                onClick={() => void move({ who: '' })}>退回待审</button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
