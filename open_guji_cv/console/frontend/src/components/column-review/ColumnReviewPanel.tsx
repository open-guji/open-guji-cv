import { useEffect, useRef, useState } from 'react'
import { postEvents } from '../../api/events'
import { api, withWorkspace } from '../../api/client'
import './column-review.css'

// Step2 列清理人裁（用户 2026-09-17）。两个方向、两种裁法：
//   左右：拖两条竖线出 human_left/right —— 边界是一条**走廊**不是一个点，
//         人拖到的是保守端（金标 README：拖到墨占比仍 ≈0 的最远处）。
//   上下：只选**类别**，不给可拖的线 —— README 明写「印上去会把人的判断
//         带偏，而要量的正是人怎么分类」。
//
// 抽样按分诊类别分层、**故意超采样难例**，所以这批不能当全书比例的估计。
// 裁决走既有事件链路（POST /api/events，kind="column_band"），不新造协议。

type Triage = {
  side_class: string; top_class: string; bot_class: string
  pad_top: number; pad_bottom: number
}
type Case = {
  id: string; book: string; page: number; col: number
  triage: Triage; band: [number, number]
  trim_top: { px: number; case: string }; trim_bottom: { px: number; case: string }
  size: [number, number]; raised: boolean; img: string
}
type Verdict = {
  human_left?: number; human_right?: number
  top_class?: string; bot_class?: string
  side_verdict?: string; note?: string
}

// 选项顺序：**最常见的正确答案排第一**（用户 2026-09-17）。人裁几百列时，
// 正确项在第一位能少移一次鼠标；也与下面的「默认预选」对齐——预选的就是第一项。
const END_CLASSES = [
  { k: 'clean', label: '有框·有间隙', hint: '框与首字之间断得开' },
  { k: 'none', label: '无框墨', hint: '边缘没有版框残墨' },
  { k: 'glued', label: '有框·粘字', hint: '框和字连在一起，切不出界' },
  { k: 'idk', label: '拿不准', hint: '' },
]
const SIDE_VERDICTS = [
  { k: 'clean', label: '两侧都对', hint: '红线落在字外的空白里，留一点界行残墨是预期的' },
  { k: 'eat', label: '切到字了', hint: '红线切进字身' },
  { k: 'mixed', label: '没有零区', hint: '一路都有墨，标不出唯一坐标' },
  { k: 'idk', label: '拿不准' },
]

//: 进卡就预选的默认值（用户 2026-09-17：「没问题我就什么不选直接进下一个」）。
//: **翻过即认可**——用户明确定过：默认值也当一条裁决存进金标，不区分「明确点选」
//: 与「默认翻过」。所以这里选的必须是**最常见的正确答案**，而不是「最安全的」：
//: 全书 1026 列里 990 列分诊为 clean，预选 clean 与实际分布一致。
const DEFAULT_VERDICT: Verdict = { top_class: 'clean', bot_class: 'clean', side_verdict: 'clean' }

function cls(t: string) {
  return t === 'eat' || t === 'glued' ? 'bad' : t === 'mixed' || t === 'idk' ? 'warn' : 'ok'
}

export function ColumnReviewPanel({ book, pages }: { book: string; pages: string }) {
  const [scope, setScope] = useState<'all' | 'blocking' | 'review'>('blocking')
  const [limit, setLimit] = useState(30)
  const [imgSrc, setImgSrc] = useState<'bin' | 'raw'>('bin')
  const [cases, setCases] = useState<Case[]>([])
  const [msg, setMsg] = useState('')
  const [cur, setCur] = useState(0)
  const verdicts = useRef<Record<string, Verdict>>({})
  const touched = useRef<Set<string>>(new Set())
  const [, bump] = useState(0)
  const rerender = () => bump((n) => n + 1)

  // 批次名**不带页范围**：列裁决是「这一列清得对不对」，与人当时挑的页范围无关。
  // 带上的话同一批裁决会因为页码框写 `3-56` 还是 `all` 分到两个批次
  // （实测踩到：5 条落在 bxgb-all-column，另一批落在 bxgb-3-56-column），
  // 「读回本批已裁」也就跟着失灵，同一列会被重复端出来裁第二遍。
  const batch = () => `${book}-column`

  async function load() {
    setMsg('载入中…')
    try {
      const qs = `book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages || 'dev_set')}`
        + `&scope=${scope}&limit=${limit}`
      const d = await api<{ cases: Case[]; counts: Record<string, number> }>(
        `/api/column-review/cases?${qs}`)
      setCases(d.cases); setCur(0)
      try {
        const v = await api<{ verdicts: Record<string, Verdict> }>(
          `/api/column-review/verdicts?batch=${encodeURIComponent(batch())}`)
        verdicts.current = { ...v.verdicts, ...verdicts.current }
      } catch { /* 批次还不存在 = 没裁过 */ }
      setMsg(`${d.cases.length} 列（全书 拦 ${d.counts.blocking} / 复审 ${d.counts.review} / 干净 ${d.counts.clean}）`)
    } catch (e) {
      setMsg(`载入失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  function setV(id: string, patch: Partial<Verdict>) {
    verdicts.current[id] = { ...(verdicts.current[id] || {}), ...patch }
    touched.current.add(id)
    rerender()
  }

  async function submit() {
    const ids = [...touched.current]
    if (!ids.length) { setMsg('没有新裁决'); return }
    setMsg('提交中…')
    try {
      // 两条纪律，都是踩出来的：
      // 1. 事件行是**扁平**的 `{id, t, ...payload}`——后端 `/api/events` 按
      //    `row["id"]` 取 key、其余字段整个当 payload。写成 `{target, payload}`
      //    会被那里的 `if not row.get("id"): continue` **静默跳过**（接口 200、
      //    appended 却是 0）。
      // 2. `kind` 是**受控枚举**，不新造。左右用既有的 `band`（拖出的边界）、
      //    上下用 `border_class`（类别裁决 clean/glued/none/idk）——两个 kind
      //    在 `feedback/events.py` 里本就为这件事留着，也已有消费器。
      const t = Date.now()
      const sideRows = ids.filter((id) => verdicts.current[id]?.side_verdict)
        .map((id) => ({ id, t, band: verdicts.current[id].side_verdict }))
      const endRows = ids.filter((id) => verdicts.current[id]?.top_class || verdicts.current[id]?.bot_class)
        .map((id) => ({
          id, t,
          border_class: `top=${verdicts.current[id].top_class || '-'},bot=${verdicts.current[id].bot_class || '-'}`,
          top_class: verdicts.current[id].top_class, bot_class: verdicts.current[id].bot_class,
        }))
      if (sideRows.length) {
        await postEvents({ batch: batch(), step: 'column_warp', unit: 'column', kind: 'band', events: sideRows })
      }
      if (endRows.length) {
        await postEvents({ batch: batch(), step: 'column_warp', unit: 'column', kind: 'border_class', events: endRows })
      }
      touched.current.clear()
      setMsg(`已提交 ${ids.length} 条`)
      rerender()
    } catch (e) {
      setMsg(`提交失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  useEffect(() => { setCases([]); setMsg('') }, [book, pages])

  // 进卡就把默认值落进 verdicts 并计入 touched：**翻过即认可**（用户 2026-09-17）。
  // 不落 touched 的话，人一路翻过去 submit 时一条都不会提交——「什么不选直接进
  // 下一个」就成了「什么都没记下来」。已经裁过的（从服务端读回或本轮改过的）不覆盖。
  useEffect(() => {
    const c0 = cases[cur]
    if (!c0 || verdicts.current[c0.id]) return
    verdicts.current[c0.id] = { ...DEFAULT_VERDICT }
    touched.current.add(c0.id)
    rerender()
  }, [cur, cases])

  // ← → 翻页：「没问题就直接进下一个」的主路径，手不用离开键盘。
  // 焦点在输入框/下拉里时不接管（那时方向键是编辑用的）。
  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (!cases.length) return
      const t = ev.target as HTMLElement | null
      if (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName) && (t as HTMLInputElement).type !== 'radio') return
      if (ev.key === 'ArrowRight') { setCur((i) => Math.min(cases.length - 1, i + 1)); ev.preventDefault() }
      else if (ev.key === 'ArrowLeft') { setCur((i) => Math.max(0, i - 1)); ev.preventDefault() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [cases])

  const c = cases[cur]
  const v = c ? (verdicts.current[c.id] || {}) : {}
  const nDone = cases.filter((x) => verdicts.current[x.id]).length

  return (
    <div className="card colrev">
      <div className="colrev-bar">
        <b>列清理裁决</b>
        <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
          <option value="blocking">只看要拦的（会丢字）</option>
          <option value="review">只看要复审的</option>
          <option value="all">全部（含干净对照）</option>
        </select>
        <label>条数 <input type="number" value={limit} min={1} max={300}
                          onChange={(e) => setLimit(+e.target.value || 30)} size={4} /></label>
        <button onClick={load}>载入</button>
        <button onClick={submit} disabled={!touched.current.size}>
          提交裁决{touched.current.size ? `（${touched.current.size}）` : ''}
        </button>
        <span className="muted">{msg}</span>
      </div>

      {c && (
        <div className="colrev-body">
          <div className="colrev-nav">
            <button onClick={() => setCur((i) => Math.max(0, i - 1))} disabled={cur === 0}>←</button>
            <span>{cur + 1} / {cases.length}</span>
            <button onClick={() => setCur((i) => Math.min(cases.length - 1, i + 1))}
                    disabled={cur >= cases.length - 1}>→</button>
            <span className="muted">已认可 {nDone}</span>
            <b>{c.id}</b>
            {c.raised && <span className="tag warn">抬头列</span>}
            <span className={`tag ${cls(c.triage.side_class)}`}>左右 {c.triage.side_class}</span>
            <span className={`tag ${cls(c.triage.top_class)}`}>上 {c.triage.top_class}</span>
            <span className={`tag ${cls(c.triage.bot_class)}`}>下 {c.triage.bot_class}</span>
            <span className="muted">
              算法削 上{c.trim_top.px}px({c.trim_top.case}) / 下{c.trim_bottom.px}px({c.trim_bottom.case})
              ・左右带 [{c.band[0]}, {c.band[1]}]px / 宽{c.size[0]}
            </span>
            <label className="muted" style={{ marginLeft: 'auto' }}>
              <input type="checkbox" checked={imgSrc === 'bin'}
                     onChange={(e) => setImgSrc(e.target.checked ? 'bin' : 'raw')} /> 二值图
            </label>
          </div>

          <div className="colrev-main">
            {/* 整列图：上下端各截一段放大，中间缩略 */}
            <ColumnStrips cse={c} src={imgSrc} />
            <div className="colrev-forms">
              <fieldset>
                <legend>上端</legend>
                {END_CLASSES.map((e) => (
                  <label key={e.k} title={e.hint}>
                    <input type="radio" name={`top-${c.id}`} checked={v.top_class === e.k}
                           onChange={() => setV(c.id, { top_class: e.k })} /> {e.label}
                  </label>
                ))}
              </fieldset>
              <fieldset>
                <legend>下端</legend>
                {END_CLASSES.map((e) => (
                  <label key={e.k} title={e.hint}>
                    <input type="radio" name={`bot-${c.id}`} checked={v.bot_class === e.k}
                           onChange={() => setV(c.id, { bot_class: e.k })} /> {e.label}
                  </label>
                ))}
              </fieldset>
              <fieldset>
                <legend>左右</legend>
                {SIDE_VERDICTS.map((e) => (
                  <label key={e.k} title={e.hint || ''}>
                    <input type="radio" name={`side-${c.id}`} checked={v.side_verdict === e.k}
                           onChange={() => setV(c.id, { side_verdict: e.k })} /> {e.label}
                  </label>
                ))}
                <div className="muted">算法带 [{c.band[0]}, {c.band[1]}]，宽 {c.size[0]}</div>
              </fieldset>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// 端部各截一段放大给人看——整列缩成一条没法判「框和字断没断开」。
// 图走 `/api/column-review/img`：**二值化（Sauvola k=0.10）+ 把算法的线画上去**。
//   红=文字带左右边界（左右 padding）　绿=上端削到的行　蓝=下端削到的行
// 看不到线就没法判「削到哪了对不对」；二值化是为了与字形库/定字审阅同一把尺子
// （Step2 内部判据仍是固定阈 128，两者在本书上差 15%~38% 墨量——正因为如此，
// 人看的那张必须标明是哪一张，否则裁决对不上号）。
function ColumnStrips({ cse, src }: { cse: Case; src: 'bin' | 'raw' }) {
  const base = `/api/column-review/img/${cse.book}/${cse.page}/${cse.col}.png?src=${src}`
  const PAD = 130
  return (
    <div className="colrev-strips">
      <figure>
        <img src={withWorkspace(`${base}&end=top&pad=${PAD}`)} alt="上端" className="zoom" />
        <figcaption>上端（绿线=削到这里）</figcaption>
      </figure>
      <figure>
        <img src={withWorkspace(`${base}&end=bottom&pad=${PAD}`)} alt="下端" className="zoom" />
        <figcaption>下端（蓝线=削到这里）</figcaption>
      </figure>
      <figure className="whole">
        <img src={withWorkspace(`${base}&end=all`)} alt="整列" style={{ maxHeight: 420 }} />
        <figcaption>整列（红线=左右带）</figcaption>
      </figure>
    </div>
  )
}
