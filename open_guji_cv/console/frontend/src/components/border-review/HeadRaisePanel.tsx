import { useState } from 'react'
import { fetchHeadColCards, fetchHeadColVerdicts } from '../../api/headRaise'
import { postEvents } from '../../api/events'
import { usePersistedPages } from '../../hooks/usePersistedPages'
import type { HeadColCard, HeadColState } from '../../types/headRaise'
import { HEAD_CUT_OPTS, N_RAISED_OPTS, RAISED_OPTS } from '../../types/headRaise'
import './borderReview.css'

// 列级抬头精标（overview `Step3-逐字切分/03-抬头综合优化.md`）。
//
// 为什么不复用 BorderReviewPanel：那个面板是「一张图 + 一排按钮选一档，点完
// 即落事件」，这里一张卡要答三件事（是不是抬头 / 抬高几格 / 首字有没有被切
// 掉），而且**三件事要一起落一条事件**——分三条事件会让金标里出现"只答了
// 一半"的条目，`n_raised` 的分布统计就没法用了。
//
// 落事件用 `kind: 'head_raise'`，**不是 `verdict`**：`verdict` +
// `step=row_segment` 已经被路由表占着，会一并灌进 `char-segmentation/row-boundaries`
// ——那个分片是旧坐标系、已退役。

const STEP = 'row_segment'

export function HeadRaisePanel({ book }: { book: string }) {
  const [pages, setPages] = usePersistedPages('headcol', book, 'dev_set')
  const [batchInput, setBatchInput] = useState('')
  const [onlyTodo, setOnlyTodo] = useState(true)
  const [onlySuspect, setOnlySuspect] = useState(false)
  // 叠线默认开：不叠的那版实测「无法判定几格、首字是否完整」（用户 2026-09-12）。
  // 留开关是因为有时想看纯原图确认线本身画得对不对。
  const [overlay, setOverlay] = useState(true)
  const [cards, setCards] = useState<HeadColCard[]>([])
  const [states, setStates] = useState<Record<string, HeadColState>>({})
  const [msg, setMsg] = useState('')

  const batch = () => batchInput.trim() || `${book}-headcol-review`

  async function load() {
    setMsg('载入中…')
    const b = batch()
    let d
    try {
      d = await fetchHeadColCards(book, pages || 'dev_set')
    } catch (e) {
      setMsg('失败：' + (e as Error).message)
      return
    }
    let done: Awaited<ReturnType<typeof fetchHeadColVerdicts>>['verdicts'] = {}
    try {
      done = (await fetchHeadColVerdicts(b)).verdicts || {}
    } catch {
      // 新批次，没有裁决可读
    }
    const st: Record<string, HeadColState> = {}
    for (const c of d.cards) {
      const v = done[c.id]
      if (!v) continue
      st[c.id] = {
        raised: (v.raised || v.verdict) as HeadColState['raised'],
        nRaised: v.n_raised ?? undefined,
        headCut: (v.head_cut || undefined) as HeadColState['headCut'],
        done: true,
      }
    }
    setStates(st)
    setCards(d.cards)
    setMsg(`${d.n} 张卡 → 批次 ${b}`)
  }

  /** 三件事都答了才算完整——缺一项就别落事件，金标里不该有半截条目。 */
  function complete(s: HeadColState | undefined): boolean {
    if (!s?.raised || !s.headCut) return false
    if (s.raised === 'yes' && s.nRaised == null) return false
    return true
  }

  function patch(c: HeadColCard, d: Partial<HeadColState>) {
    setStates((prev) => {
      const next = { ...prev, [c.id]: { ...prev[c.id], ...d } }
      const s = next[c.id]
      // 判「不是抬头」就把格数清掉：后端也不会落这个键，UI 留着会误导
      if (s.raised === 'no' || s.raised === 'idk') delete s.nRaised
      if (complete(s) && !s.done) void submit(c, s)
      return next
    })
  }

  async function submit(c: HeadColCard, s: HeadColState) {
    try {
      await postEvents({
        batch: batch(), step: STEP, unit: 'column', kind: 'head_raise',
        events: [{
          id: c.id, raised: s.raised, head_cut: s.headCut,
          ...(s.raised === 'yes' ? { n_raised: s.nRaised } : {}),
          t: Date.now(),
        }],
      })
      setStates((p) => ({ ...p, [c.id]: { ...p[c.id], done: true } }))
      setMsg(`已裁 ${Object.values(states).filter((x) => x.done).length + 1} / ${cards.length} → 批次 ${batch()}`)
    } catch (e) {
      setMsg('写入失败：' + (e as Error).message)
    }
  }

  // 两个标记都由后端给（见 border_cards.py）：
  //   detected = Step1 探到抬头框，**权威判据**（18 列金标 15 命中零误报）
  //   suspect  = 探测器没报但框上字墨很多，**疑似漏检**，优先人裁
  // 「只看待裁的」＝这两类，普通列不出现。
  const flagged = (c: HeadColCard) => c.detected || c.suspect

  const visible = cards
    .filter((c) => (onlyTodo ? !states[c.id]?.done : true))
    .filter((c) => (onlySuspect ? flagged(c) : true))

  const nDone = Object.values(states).filter((s) => s.done).length

  return (
    <div className="card">
      <h2>列级抬头精标 <span className="muted">一列一张，判抬头 + 几格 + 首字有没有被切掉</span></h2>
      <p className="muted br-howto">
        每张卡是<b>一列</b>上版框那一段的原图，叠了三层线：
        <b style={{ color: '#0a78eb' }}> 蓝＝整页上内边框</b>、
        <b style={{ color: '#ff9600' }}> 橙虚线＝本列抬头内边框</b>（没画=Step1 没探到）、
        <b style={{ color: '#dc3c3c' }}> 红＝格子切分线</b>。看三件事：
        ①这一列是不是抬头（判据是<b>字写到了蓝线以上</b>，不是"比邻列高一点"）；
        ②抬高几格（<b>数蓝线以上有几条红线围出的格</b>）；
        ③<b>首字有没有被切掉</b>——如果最上面那个字没有被红线完整框住、
        只剩半截或整个落在首条红线之外，点"首字被切"。三项都选完自动保存。
        标题上两种标记：<b style={{ color: '#3a7d44' }}>已探到抬头框</b>＝Step1
        的抬头框探测器报了（水平投影找内外边框＋墙线校验，18 列金标 15 命中零误报）；
        <b style={{ color: '#b4433a' }}>疑似漏检</b>＝探测器没报、但框上字墨很多，
        <b>这类最值得裁</b>——它量的正是探测器的漏检率。
      </p>
      <div className="br-toolbar">
        <label className="muted">页 <input value={pages} onChange={(e) => setPages(e.target.value)} size={10} /></label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册自动命名" /></label>
        <label className="muted"><input type="checkbox" checked={onlyTodo} onChange={(e) => setOnlyTodo(e.target.checked)} /> 只看未裁</label>
        <label className="muted"><input type="checkbox" checked={onlySuspect} onChange={(e) => setOnlySuspect(e.target.checked)} /> 只看抬头/疑似列</label>
        <label className="muted"><input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} /> 叠几何线</label>
        <button onClick={load}>载入</button>
        <span className="muted">{msg}{cards.length ? `（已裁 ${nDone}）` : ''}</span>
      </div>
      <div className="brgrid">
        {visible.map((c) => {
          const s = states[c.id] || {}
          return (
            <article key={c.id} className="brcard hrcard" data-v={s.done ? (s.raised || '') : ''}>
              <h3>
                {c.book}/{c.page} <em>第 {c.col} 列</em>
                {c.detected && <em className="hr-det-tag">已探到抬头框</em>}
                {c.suspect && <em className="hr-susp">疑似漏检</em>}
              </h3>
              {/* 不用 loading=lazy：图在可滚动的 .hr-img-wrap 里，懒加载遇上
                  「容器还没高度」会整排不触发（实测 9 张卡只显示第 1 张）。
                  一页 9 张列带图，直接加载代价可以接受。 */}
              <div className="hr-img-wrap">
                <img src={`${c.img}&overlay=${overlay ? 1 : 0}`} alt="" />
              </div>
              <div className="hr-row">
                <span className="hr-lab">抬头</span>
                {RAISED_OPTS.map((o) => (
                  <button key={o.key} aria-pressed={s.raised === o.key}
                          style={s.raised === o.key ? { background: o.soft, borderColor: o.color, color: o.color } : undefined}
                          onClick={() => patch(c, { raised: o.key })}>{o.label}</button>
                ))}
              </div>
              {s.raised === 'yes' && (
                <div className="hr-row">
                  <span className="hr-lab">几格</span>
                  {N_RAISED_OPTS.map((n) => (
                    <button key={n} aria-pressed={s.nRaised === n}
                            style={s.nRaised === n ? { background: 'var(--indigo-soft)', borderColor: 'var(--indigo)', color: 'var(--indigo)' } : undefined}
                            onClick={() => patch(c, { nRaised: n })}>{n}</button>
                  ))}
                </div>
              )}
              <div className="hr-row">
                <span className="hr-lab">首字</span>
                {HEAD_CUT_OPTS.map((o) => (
                  <button key={o.key} aria-pressed={s.headCut === o.key}
                          style={s.headCut === o.key ? { background: o.soft, borderColor: o.color, color: o.color } : undefined}
                          onClick={() => patch(c, { headCut: o.key })}>{o.label}</button>
                ))}
              </div>
              <p className="hr-det muted">
                现役：{c.det_raised ? '抬头' : '非抬头'} · n_raised {c.det_n_raised ?? '—'} ·
                slack {c.det_top_slack ?? '—'} ·
                抬头内边框 {c.det_hr_inner ?? '未探到'} · 框上字墨 {c.ink_rows} 行 ·
                首格 {c.det_first_cell ? `slot ${c.det_first_cell.slot} ${c.det_first_cell.kind} y0=${c.det_first_cell.y0}` : '—'}
                {s.done && <b className="hr-ok"> ✓ 已存</b>}
              </p>
            </article>
          )
        })}
      </div>
    </div>
  )
}
