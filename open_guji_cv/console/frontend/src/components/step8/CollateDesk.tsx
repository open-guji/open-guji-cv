import { useCallback, useEffect, useState } from 'react'
import { withWorkspace } from '../../api/client'
import { fetchStep8Overview, fetchStep8Pairs, postStep8Decide } from '../../api/step8'
import type { Step8Overview, Step8Pair, Step8Sample, Step8Tier } from '../../api/step8'

// Step8 · 复核裁决台。设计见 overview 仓 Step8-落库反馈/05。
//
// 与 Step7 定字裁决台的分工（这是本组件存在的理由）：
//   Step7 问「这是什么字」，卡来自 seed_admit 说「我不确定」，是闸；
//   Step8 问「我们和校对本谁对」，卡来自对勘说「你跟校对本不一样」，**不 block 下一步**。
//
// 各层**不是各自的页签，是同一个队列里的几种卡片**——人的判断是连续的：
// 看到 甫→父 会想「这是本书通例」，看到 開→聞 会想「这是认错」，中间不该切页面。
//
// ⭐ 按**字对**聚合，不按条：𠊓→傍 一对就占 24 条，逐条问等于把同一个问题问 24 遍。

const TIER_ORDER: Step8Tier[] = ['dispute', 'book', 'variant', 'jiajie', 'taboo']

// ③ 零星分歧是**两级**裁决（用户 2026-09-22）：
//   第一级答「谁对」，第二级答「这是什么关系」。
// 分两级是因为这两个问题独立：「我方对」之后仍可能是通假（甫/父，两边都没错）
// 或不同字（開/聞，对方错了）。合成一级会逼人在「谁对」里塞进关系判断。
const WHO = [
  { key: 'ours', label: '我方对', hint: '转写忠于刻本' },
  { key: 'theirs', label: '校对本对', hint: '我们认错了，改字并入库' },
  { key: 'neither', label: '都不对', hint: '两边都错，输入正确的字' },
] as const
// 「不同字」排在前面且是默认值：③ 里绝大多数就是这个（實測 64 对里只有零星
// 几对是通假）。默认选中最常见的那档，人只在**例外**时才动手——这是把 64 次
// 判断压成「翻页 + 偶尔改一下」的关键。
const REL = [
  { key: 'diff', label: '不同字', hint: '就是两个字，一方认错了' },
  { key: 'jiajie', label: '通假字', hint: '本字不在、借另一个字代替 → 移入通假字' },
] as const

//: ③ 的默认裁决：我方对 · 不同字。**默认展开且选中**，回车/→ 直接确认。
const DEFAULT_WHO = 'ours'
const DEFAULT_REL = 'diff' 

// ② 本书特有：选一个性质即批量确认。**异体也是一项**——通用异体表有缺漏，
// 有些字对表里没收但确实是异体（用户 2026-09-22）。
const BOOK_KINDS = ['人名', '物品', '通假', '异体', '避諱', '正俗'] as const

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
      <div className="s8-stat"><b>{agree}%</b><span>与校对本一致</span></div>
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
  // 「N 处一起裁」：勾上一次定全部；不勾**只裁当前这一处**，卡片留在队列里
  // 等剩下的 N-1 处（用户 2026-09-22：「不勾应该裁两次」）。
  const [applyAll, setApplyAll] = useState(true)
  const [at, setAt] = useState(0)          // 不勾一起裁时，裁到该字对的第几处
  const [who, setWho] = useState(DEFAULT_WHO)   // ③ 第一级，默认「我方对」
  const [rel, setRel] = useState(DEFAULT_REL)   // ③ 第二级，默认「不同字」
  const [fix, setFix] = useState('')       // 「都不对」时人输入的字

  const load = useCallback(async () => {
    if (!book) return
    setBusy(true); setMsg('')
    try {
      const [o, p] = await Promise.all([fetchStep8Overview(book), fetchStep8Pairs(book, tier)])
      setOv(o); setPairs(p.pairs || []); setCur(0); setAt(0)
      setWho(DEFAULT_WHO); setRel(DEFAULT_REL); setFix('')
      if (!o.has_report) setMsg(o.hint || '还没有对勘产物')
    } catch (e) { setMsg(String(e)) } finally { setBusy(false) }
  }, [book, tier])

  useEffect(() => { void load() }, [load])

  const c = pairs[cur]
  const nextCard = () => {
    setWho(DEFAULT_WHO); setRel(DEFAULT_REL); setFix(''); setAt(0)
    setCur((i) => Math.min(i + 1, pairs.length - 1))
  }
  // 不勾一起裁：走完这一对的 N 处才翻下一张卡
  const advance = () => {
    if (!c) return
    if (applyAll || at + 1 >= c.n) { nextCard(); return }
    setAt((i) => i + 1); setWho(DEFAULT_WHO); setRel(DEFAULT_REL); setFix('')
  }

  // 「下一个」= **确认当前选择**（用户 2026-09-23）。③ 默认「我方对·不同字」，
  // 于是一路回车/→ 就能把那批「我们没错、就是两个字」的快速走完，
  // 只在例外时才动手改选项——这是把 64 次判断压成「翻页 ＋ 偶尔改一下」的关键。
  //
  // 「都不对」还没填字时不提交（否则会写一条空 shape 的 confirm），只翻页。
  const confirmNext = async () => {
    if (!c) return
    if (c.tier === 'dispute' && who === 'neither' && !fix) { nextCard(); return }
    await submit()
  }

  // `ids`：勾了一起裁就全部，否则只当前这一处（用户 2026-09-22：「不勾应该裁两次」）。
  const submit = async (opt: { rel?: string; kind?: string } = {}) => {
    if (!c || busy) return
    // ③ 不传 rel 时用当前选中的（默认「不同字」）——回车/→ 走的就是这条。
    if (c.tier === 'dispute' && opt.rel === undefined && who !== 'neither') opt.rel = rel
    const ids = applyAll ? c.ids : [c.ids[at]]
    setBusy(true)
    try {
      const r = await postStep8Decide({
        book, pair: c.pair, ids, who, rel: opt.rel, kind: opt.kind, fix,
      })
      if (!r.ok) { setMsg(r.error || '提交失败'); return }
      const done = (r.consumed || []).map((x) => `${x.consumer} ${x.added}`).join('、')
      setMsg(`${c.pair[0]}→${c.pair[1]} × ${ids.length} 处已写入`
        + `${done ? '；已落库（' + done + '）' : ''}`
        + `${r.consume_error ? '；⚠ 消费失败 ' + r.consume_error : ''}`)
      advance()
    } catch (e) { setMsg(String(e)) } finally { setBusy(false) }
  }

  // 键盘走查（用户 2026-09-23：「回车或向右键，等于确认」）。
  // 在输入框里打字时不接管——「都不对」填字那里的回车由 input 自己处理。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      if (e.key === 'Enter' || e.key === 'ArrowRight') { e.preventDefault(); void confirmNext() }
      else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setWho(DEFAULT_WHO); setRel(DEFAULT_REL); setFix(''); setAt(0)
        setCur((i) => Math.max(0, i - 1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

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
          <b>校对本无此段 {ov.absent_runs.length}</b>
          <span className="muted">校勘按语、卷端题、卷末题之类——校对本另有体例、不收。
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
            {(applyAll ? c.samples : c.samples.slice(at, at + 1)).map((s) => (
              <img key={s.id} src={patchUrl(book, s)} alt={s.id} title={s.id} />
            ))}
          </div>
          <div className="s8-pair">
            <span className="gl big">{c.pair[0]}</span><span className="arr">→</span>
            <span className="gl big">{c.pair[1]}</span>
            <span className="s8-n">全书 {c.n} 处{!applyAll && c.n > 1 ? ` · 正在裁第 ${at + 1}` : ''}</span>
            <span className="muted">p{c.pages.slice(0, 6).join('、')}{c.pages.length > 6 ? '…' : ''}</span>
          </div>
          {(applyAll ? c.samples : c.samples.slice(at, at + 1)).map((s) => (
            <div key={s.id} className="s8-ctx">
              <div><span className="k">我方</span><span className="gl">{s.hyp_ctx}</span></div>
              <div><span className="k">校对本</span><span className="gl">{s.ref_ctx}</span></div>
            </div>
          ))}

          {c.tier === 'dispute' ? (
            <>
              <div className="s8-acts">
                {WHO.map((a) => (
                  <button key={a.key} title={a.hint}
                    className={who === a.key ? 'on' : ''}
                    onClick={() => setWho(a.key)}>{a.label}</button>
                ))}
                {c.n > 1 && (
                  <label><input type="checkbox" checked={applyAll}
                    onChange={(e) => { setApplyAll(e.target.checked); setAt(0) }} /> {c.n} 处一起裁</label>
                )}
              </div>
              {who === 'neither' && (
                <div className="s8-acts">
                  <input className="s8-fix" value={fix} maxLength={4} placeholder="正确的字"
                    autoFocus
                    onChange={(e) => setFix(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && fix) void submit() }} />
                  <button disabled={!fix} onClick={() => void submit()}>提交</button>
                </div>
              )}
              {(who === 'ours' || who === 'theirs') && (
                <div className="s8-acts">
                  <span className="k">这一对是</span>
                  {REL.map((r) => (
                    <button key={r.key} title={r.hint}
                      className={rel === r.key ? 'on' : ''}
                      onClick={() => setRel(r.key)}>{r.label}</button>
                  ))}
                  <span className="s8-hint">↵ 或 → 确认并下一对</span>
                </div>
              )}
            </>
          ) : (
            <div className="s8-acts">
              {c.tier === 'book' && BOOK_KINDS.map((k) => (
                <button key={k} onClick={() => void submit({ kind: k })}>{k}</button>
              ))}
              {c.tier === 'variant' && (<>
                <button onClick={() => { setWho('ours'); void submit({ rel: 'diff' }) }}>确认是异体</button>
                <button title="本字不在、借另一个字代替 → 移入通假字"
                  onClick={() => void submit({ rel: 'jiajie' })}>这是通假</button>
                <button title="写进 variants.deny.tsv，任何书都不再当异体"
                  onClick={() => void submit({ kind: '不是异体' })}>不是异体·要改</button>
              </>)}
              {c.tier === 'jiajie' && <button
                onClick={() => { setWho('ours'); void submit({ rel: 'jiajie' }) }}>确认是通假</button>}
              {c.tier === 'taboo' && <button
                onClick={() => { setWho('ours'); void submit({}) }}>确认是避諱</button>}
              {c.tier === 'book' && (
                <button title="退回零星分歧逐条判"
                  onClick={() => void submit({ kind: 'dispute' })}>不是通例</button>
              )}
              {c.n > 1 && (
                <label><input type="checkbox" checked={applyAll}
                  onChange={(e) => { setApplyAll(e.target.checked); setAt(0) }} /> {c.n} 处一起裁</label>
              )}
            </div>
          )}

          <div className="s8-nav">
            <button title="上一对（不提交）"
              onClick={() => { setWho(DEFAULT_WHO); setRel(DEFAULT_REL); setFix(''); setAt(0); setCur((i) => Math.max(0, i - 1)) }}
              disabled={cur === 0}>←</button>
            <button title="确认当前选择并下一对" onClick={() => void confirmNext()}>→</button>
          </div>
        </div>
      )}
    </div>
  )
}
