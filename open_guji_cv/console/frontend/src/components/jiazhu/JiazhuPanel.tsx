import { useState } from 'react'
import { fetchJiazhuSegments } from '../../api/jiazhu'
import { postEvents } from '../../api/events'
import { needsReading, consumedMsg } from '../../domain'
import type { JiazhuSegment } from '../../types/jiazhu'
import './jiazhu.css'

// 迁移自 v1 static/js/panels/jiazhu.js（189 行）。段是审阅单位：一段版本注
// 5–19 字，人一眼读完整句就知道通不通；逐格出卡等于把一句话拆成十几道题。
// 裁决协议原样沿用（confirm / seg_defect 事件），见方案 §一：v2 不改后端契约。

const DEFECT_OPTIONS = [
  { key: 'jiazhu_as_body', label: '夹注被当正文（整宽正文字被劈成a/b两半）', quality: 'contaminated' },
  { key: 'jiazhu_truncated', label: '夹注被截断（子列右/左缘裁进笔画）', quality: 'truncated' },
  { key: 'jiazhu_too_few', label: '少格（漏拆，字数比实际注文少）', quality: 'truncated' },
  { key: 'jiazhu_too_many', label: '多格（多切，字数比实际注文多）', quality: 'contaminated' },
  { key: 'jiazhu_ab_swapped', label: 'ab分错边', quality: 'contaminated' },
  { key: 'other', label: '其他', quality: 'contaminated' },
] as const

interface DefectChoice { key: string; quality: string; note: string }

export function JiazhuPanel({ book }: { book: string }) {
  const [pages, setPages] = useState('jz')
  const [only, setOnly] = useState<'all' | 'review' | 'auto'>('all')
  const [batchInput, setBatchInput] = useState('')
  const [segs, setSegs] = useState<JiazhuSegment[]>([])
  const [edit, setEdit] = useState<Record<string, string>>({})
  const [defect, setDefect] = useState<Record<string, DefectChoice>>({})
  const [msg, setMsg] = useState('')
  const [loaded, setLoaded] = useState(false)

  const batch = () => batchInput.trim() || `${book}-jiazhu`

  async function load() {
    setMsg('载入中…')
    try {
      const d = await fetchJiazhuSegments(book, pages || 'jz', only, batch())
      setSegs(d.segments)
      setEdit({})
      setDefect({})
      setLoaded(true)
      setMsg(`${d.pages.length} 页，段 ${d.n}（含待审 ${d.n_review}）→ 批次 ${batch()}`)
    } catch (e) {
      setMsg(String((e as Error).message ?? e))
    }
  }

  function editCell(segIdx: number, cellIdx: number) {
    const s = segs[segIdx]
    const c = s.cells[cellIdx]
    const cur = edit[c.id] !== undefined ? edit[c.id] : (c.char || '')
    const v = window.prompt(`${c.id}\n整理本：${c.ref || '—'}\n改成（留空=撤销改动）：`, cur)
    if (v === null) return
    setEdit((prev) => {
      const next = { ...prev }
      if (v.trim()) next[c.id] = v.trim()
      else delete next[c.id]
      return next
    })
  }

  function confirmSegment(segIdx: number) {
    const s = segs[segIdx]
    setEdit((prev) => {
      const next = { ...prev }
      for (const c of s.cells) if (next[c.id] === undefined) next[c.id] = c.char || ''
      return next
    })
    setMsg(`已标记整段 ${s.id}（${s.n} 格），记得点「提交裁决」`)
  }

  function markDefect(segIdx: number) {
    const s = segs[segIdx]
    const cur = defect[s.id]?.key || 'jiazhu_too_few'
    const menu = DEFECT_OPTIONS.map((o, i) => `${i + 1}. ${o.label}`).join('\n')
    const pick = window.prompt(
      `切分缺陷类型（输入序号）：\n${menu}`,
      String(DEFECT_OPTIONS.findIndex((o) => o.key === cur) + 1 || 1),
    )
    if (pick === null) return
    const idx = Number.parseInt(pick.trim(), 10) - 1
    const opt = DEFECT_OPTIONS[idx]
    if (!opt) { setMsg('序号无效，未记录'); return }
    let note: string = opt.label
    if (opt.key === 'other') {
      const free = window.prompt('具体说明：', '')
      if (free && free.trim()) note = free.trim()
    }
    setDefect((prev) => ({ ...prev, [s.id]: { key: opt.key, quality: opt.quality, note } }))
  }

  async function submit() {
    const b = batch()
    const rows: Array<Record<string, unknown>> = []
    for (const s of segs) {
      for (const c of s.cells) {
        const v = edit[c.id]
        if (v === undefined || !v) continue
        rows.push({
          id: c.id, v: 'confirm', shape: v,
          reading: needsReading(v) ? (c.ref || v) : v,
          conversion: 0, client_ts: Date.now() / 1000,
        })
      }
    }
    const defects: Array<Record<string, unknown>> = []
    for (const s of segs) {
      const why = defect[s.id]
      if (!why) continue
      defects.push({
        id: s.cells[0].id, v: 'seg_defect', quality: why.quality, defect: why.key,
        shape: s.cells[0].char || '', reading: s.cells[0].char || '',
        note: `jiazhu_split ${s.id} ${s.n}格 ${why.note}`,
        client_ts: Date.now() / 1000,
      })
    }
    if (!rows.length && !defects.length) { setMsg('还没有裁决'); return }
    setMsg('提交中…')
    let n = 0
    let extra = ''
    try {
      if (rows.length) {
        const r = await postEvents({ batch: b, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
        n += r.appended ?? rows.length
        extra += consumedMsg(r)
      }
      if (defects.length) {
        const r2 = await postEvents({ batch: b, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: defects })
        n += r2.appended ?? defects.length
      }
    } catch (e) {
      setMsg('提交失败：' + (e as Error).message)
      return
    }
    setMsg(`已写入 ${n} 条事件 → 批次 ${b}${extra}`)
    setEdit({})
    setDefect({})
    load()
  }

  return (
    <div className="card">
      <h2>夹注 <span className="muted">雙行小注按<b>段</b>审：一段是一句话，逐格出卡等于把一句话拆成十几道题</span></h2>
      <div className="jz-toolbar">
        <label className="muted">页 <input value={pages} onChange={(e) => setPages(e.target.value)} size={10} title="jz = 夹注专项集；也可 all / 3-6,9" /></label>
        <label className="muted">范围
          <select value={only} onChange={(e) => setOnly(e.target.value as typeof only)}>
            <option value="all">全部段</option>
            <option value="review">只看含待审的段</option>
            <option value="auto">只抽查全自动的段</option>
          </select>
        </label>
        <label className="muted">批次 <input value={batchInput} onChange={(e) => setBatchInput(e.target.value)} size={22} placeholder="留空 = 按册自动命名" /></label>
        <button onClick={load}>载入</button>
        <button onClick={submit}>提交裁决</button>
        <span className="muted">{msg}</span>
      </div>
      <p className="muted jz-help">
        每张卡 = 一段夹注。<b>整段确认</b>（读序与整理本一致时一键放行，逐格发 confirm 事件）·
        点<b>某一格</b>改字（只改那一格）· <b>标切分缺陷</b>（少格/多格/ab 分错边 → seg_defect
        落段首格，quality=<span className="mono">contaminated</span>，段况写进 note）。转写下面那行是<b>整理本</b>对应注文，
        <span className="mono jz-red">红</span>=待审格，
        <span className="mono jz-mute">灰</span>=自动放行。
        a 是<b>右</b>子列先读、b 是左子列——图上从右往左看。
      </p>
      {loaded && segs.length === 0 && <div className="muted">没有夹注段</div>}
      <div>
        {segs.map((s, i) => {
          const same = s.ref && s.ref.replace(/·/g, '') === s.text.replace(/□/g, '')
          const dfl = defect[s.id]
          return (
            <div className="jzcard" key={s.id}>
              <div className="jzhead">
                <span className="mono">{s.id}</span>{' '}
                {s.n_review
                  ? <span className="badge b-pending">待审 {s.n_review}</span>
                  : <span className="badge b-completed">全自动</span>}
                <span className="muted">{s.n} 格 · a {s.a.length} / b {s.b.length}</span>
                {same
                  ? <span className="badge b-completed">与整理本一致</span>
                  : <span className="badge b-pending">与整理本有出入</span>}
              </div>
              <div className="jzbody">
                <img className="jzstrip" src={s.img} alt="列条" loading="lazy" />
                <div className="jztext">
                  <div className="jzline">
                    <span className="jzlab">转写</span>
                    {s.cells.map((c, j) => {
                      const ed = edit[c.id]
                      const shown = ed !== undefined ? ed : (c.char || '□')
                      const cls = ed !== undefined ? 'jzc-edit' : (c.admit ? 'jzc-auto' : 'jzc-rev')
                      const ref = c.ref && c.ref !== shown ? <span className="jzref">{c.ref}</span> : null
                      return (
                        <span key={c.id} className={`jzcell ${cls}`} title={`${c.id} · ${c.channel || '待审'}`}
                              onClick={() => editCell(i, j)}>
                          <img src={c.patch} alt="" loading="lazy" /><b>{shown}</b>{ref}
                        </span>
                      )
                    })}
                  </div>
                  <div className="jzline"><span className="jzlab">整理本</span><span className="mono jzrefline">{s.ref || '—'}</span></div>
                  <div className="jzacts">
                    <button onClick={() => confirmSegment(i)}>整段确认</button>
                    <button className={dfl ? 'on' : ''} onClick={() => markDefect(i)}>
                      标切分缺陷{dfl ? `（${dfl.note}）` : ''}
                    </button>
                    <span className="muted jzhint">点某一格可改字</span>
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
