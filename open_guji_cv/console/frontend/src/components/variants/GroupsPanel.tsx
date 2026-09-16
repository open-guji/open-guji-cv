import { useEffect, useRef, useState } from 'react'
import { fetchVariantGroups } from '../../api/variants'
import { submitRun, fetchRun } from '../../api/runs'
import { postEvents } from '../../api/events'
import { needsReading, consumedMsg } from '../../domain'
import { usePersistedPages } from '../../hooks/usePersistedPages'
import type { GroupTile, VariantGroupView } from '../../types/variants'
import './variants.css'

// 迁移自 v1 static/js/panels/groups.js（250 行）。一组一屏：列 = 形，格 = 图块。
// 首例确认与字形保真抽审都在这里；裁决走 confirm 事件，与单卡裁决同一条路由。

interface TileState {
  col: string
  orig?: string
  mark: '' | 'non' | 'truncated' | 'contaminated'
  changed: boolean
  other?: boolean
  otherChar?: string
}

export function GroupsPanel({ book }: { book: string }) {
  const [pages, setPages] = usePersistedPages('variants-groups', book, 'dev_set')
  const [data, setData] = useState<VariantGroupView[] | null>(null)
  const [cur, setCur] = useState<number | null>(null)
  const [stat, setStat] = useState('')
  const [staleMsg, setStaleMsg] = useState('')
  const [resyncing, setResyncing] = useState(false)
  const [msg, setMsg] = useState('')
  const [renderTick, forceRender] = useState(0)
  const bump = () => forceRender((n) => n + 1)

  const tileState = useRef<Record<string, TileState>>({})
  const selRef = useRef<string | null>(null)
  const stalePagesRef = useRef<number[]>([])

  // 换列会把格子挪到另一个 .vcol 容器下，React 视为新节点重新挂载，
  // 原生 DOM 焦点会丢——对应 v1 vgRender 结尾"重绘后把焦点还回选中的那一格"。
  useEffect(() => {
    if (!selRef.current) return
    const el = document.querySelector<HTMLElement>(`.vtile[data-id="${CSS.escape(selRef.current)}"]`)
    el?.focus({ preventScroll: true })
  }, [renderTick])

  async function load() {
    setStat('读取中…')
    let d: VariantGroupView[]
    try {
      d = (await fetchVariantGroups(book, pages.trim() || 'dev_set')).groups
    } catch (e) {
      setStat((e as Error).message)
      return
    }
    setData(d)
    setCur(null)
    tileState.current = {}
    selRef.current = null
    const nPending = d.reduce((a, g) => a + g.n_pending, 0)
    const nAuto = d.reduce((a, g) => a + (g.n_tiles - g.n_pending), 0)
    const nStale = d.reduce((a, g) => a + g.n_stale, 0)
    setStat(`${d.length} 组 · 待审 ${nPending} 格 · 已自动放行 ${nAuto} 格` + (nStale ? ` · 已裁待重跑 ${nStale} 格` : ''))
    stalePagesRef.current = [...new Set(d.flatMap((g) => g.tiles.filter((t) => t.stale).map((t) => t.page)))].sort((a, b) => a - b)
    setStaleMsg(nStale
      ? `⟳ 有 ${nStale} 格你已经裁过、但产物还是上次跑管线时的结果（黄框）——裁决没丢，已经在库里，只是这张视图读的是产物。`
      : '')

    const story = (g: VariantGroupView) =>
      g.n_pending > 0 || g.n_stale > 0 || g.n_audit > 0 ||
      new Set(g.tiles.filter((t) => t.char).map((t) => t.char)).size >= 2 ||
      g.tiles.some((t) => t.reading && t.char && t.reading !== t.char)
    const mainIdx = d.map((g, k) => [g, k] as const).filter(([g]) => story(g)).map(([, k]) => k)
    if (mainIdx.length) show(mainIdx[0], d)
    else if (d.length) show(0, d)
  }

  async function resync() {
    const pages2 = stalePagesRef.current.join(',')
    if (!pages2) return
    setResyncing(true)
    try {
      const job = await submitRun({ book, pipeline: 'keben_body_v2', from_step: 'glyph_match', pages: pages2, force: true })
      for (let i = 0; i < 240; i++) {
        await new Promise((r) => setTimeout(r, 1000))
        const j = await fetchRun(job.id)
        setStaleMsg(`重跑中… ${j.duration ? j.duration + 's' : ''}`)
        if (['completed', 'failed', 'cancelled'].includes(j.status)) {
          if (j.status !== 'completed') {
            setStaleMsg(`重跑 ${j.status}（exit ${j.exit_code}）：去「运行」页看日志`)
            setResyncing(false)
            return
          }
          break
        }
      }
      await load()
    } catch (e) {
      setStaleMsg('重跑失败：' + (e as Error).message)
    } finally {
      setResyncing(false)
    }
  }

  function show(k: number, d?: VariantGroupView[]) {
    const list = d ?? data
    if (!list) return
    const g = list[k]
    setCur(k)
    selRef.current = null
    for (const t of g.tiles) {
      if (!tileState.current[t.id]) {
        tileState.current[t.id] = { col: t.char || g.preferred || g.members[0], orig: t.char, mark: '', changed: false }
      }
    }
    bump()
  }

  function moveCol(g: VariantGroupView, id: string, dir: 1 | -1) {
    const s = tileState.current[id]
    if (s.other) return
    const cols = g.members
    const i = cols.indexOf(s.col)
    s.col = cols[(i + dir + cols.length) % cols.length]
    s.changed = s.col !== s.orig
    s.mark = ''
    bump()
  }

  function toggleOther(id: string) {
    const s = tileState.current[id]
    s.other = !s.other
    s.mark = ''
    s.changed = !!s.other || s.col !== s.orig
    selRef.current = id
    bump()
  }

  function setMark(id: string, m: TileState['mark']) {
    const s = tileState.current[id]
    s.mark = s.mark === m ? '' : m
    s.changed = true
    selRef.current = id
    bump()
  }

  function onTileKeyDown(g: VariantGroupView, t: GroupTile, ev: React.KeyboardEvent) {
    const k = ev.key.toLowerCase()
    selRef.current = t.id
    if (ev.key === 'ArrowRight' || ev.key === ' ' || ev.key === 'Enter') { ev.preventDefault(); moveCol(g, t.id, 1); return }
    if (ev.key === 'ArrowLeft') { ev.preventDefault(); moveCol(g, t.id, -1); return }
    if (k === 'o') { ev.preventDefault(); toggleOther(t.id); return }
    if (k === 'n') { ev.preventDefault(); setMark(t.id, 'non'); return }
    if (k === 't') { ev.preventDefault(); setMark(t.id, 'truncated'); return }
    if (k === 'c') { ev.preventDefault(); setMark(t.id, 'contaminated'); return }
  }

  async function send(all: boolean) {
    if (cur === null || !data) return
    const g = data[cur]
    const now = Date.now()
    const rows: Array<Record<string, unknown>> = []
    let skipped = 0
    for (const t of g.tiles) {
      const s = tileState.current[t.id]
      if (!all && !t.pending && !s.changed) continue
      if (s.mark === 'non') { rows.push({ id: t.id, v: 'not_a_char', client_ts: now }); continue }
      if (s.mark === 'truncated' || s.mark === 'contaminated') {
        const dshape = s.col
        rows.push({
          id: t.id, v: 'seg_defect', quality: s.mark,
          shape: dshape, reading: needsReading(dshape) ? (g.reading_default || dshape) : dshape,
          client_ts: now,
        })
        continue
      }
      if (s.other) {
        if (!s.otherChar) { skipped++; continue }
        rows.push({ id: t.id, v: 'confirm', shape: s.otherChar, reading: s.otherChar, conversion: 0, client_ts: now, group: 'out:' + g.canonical })
        continue
      }
      const shape = s.col
      const reading = needsReading(shape)
        ? (t.reading && t.reading !== t.char ? t.reading : (g.reading_default || shape))
        : shape
      rows.push({ id: t.id, v: 'confirm', shape, reading: reading || shape, conversion: (reading && reading !== shape) ? 1 : 0, client_ts: now, group: g.canonical })
    }
    if (!rows.length) { setMsg(skipped ? `组外那 ${skipped} 格还没填字` : '没有要提交的格'); return }
    const batch = `${book}-variants-${g.canonical}`
    setMsg(`提交 ${rows.length} 条…`)
    try {
      const r = await postEvents({ batch, step: 'seed_admit', unit: 'cell', kind: 'confirm', events: rows })
      setMsg(`已写 ${r.appended} 条到批次 ${batch}` + (skipped ? `（组外 ${skipped} 格没填字，跳过）` : '') + consumedMsg(r))
      for (const row of rows) {
        const s = tileState.current[row.id as string]
        s.orig = s.col
        s.changed = false
      }
      for (const t of g.tiles) {
        if (rows.some((r) => r.id === t.id)) { t.pending = false; t.human = tileState.current[t.id].col }
      }
      bump()
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  const g = cur !== null && data ? data[cur] : null
  const cols = g ? g.members : []
  const byCol: Record<string, GroupTile[]> = {}
  const others: GroupTile[] = []
  if (g) {
    for (const c of cols) byCol[c] = []
    for (const t of g.tiles) {
      const s = tileState.current[t.id]
      if (s.other) { others.push(t); continue }
      ;(byCol[s.col] || (byCol[s.col] = [])).push(t)
    }
  }

  const story = (gr: VariantGroupView) =>
    gr.n_pending > 0 || gr.n_stale > 0 || gr.n_audit > 0 ||
    new Set(gr.tiles.filter((t) => t.char).map((t) => t.char)).size >= 2 ||
    gr.tiles.some((t) => t.reading && t.char && t.reading !== t.char)
  const mainList = data ? data.map((gr, k) => [gr, k] as const).filter(([gr]) => story(gr)) : []
  const restList = data ? data.map((gr, k) => [gr, k] as const).filter(([gr]) => !story(gr)) : []

  const groupBtn = (gr: VariantGroupView, k: number) => (
    <button key={k} className={`vgbtn${cur === k ? ' active' : ''}`} onClick={() => show(k)}>
      <span className="vgl">{gr.canonical}</span> {gr.members.filter((m) => m !== gr.canonical).join(' ')}
      <sub>{gr.n_tiles}{gr.n_pending ? ` · 待审 ${gr.n_pending}` : ''}{gr.n_audit ? ` · 待抽审 ${gr.n_audit}` : ''}{gr.n_stale ? ` · 待重跑 ${gr.n_stale}` : ''}</sub>
    </button>
  )

  return (
    <div className="card">
      <h2>组视图 <span className="muted">一组一屏：列 = 形，格 = 图块。首例确认与字形保真抽审都在这里；裁决走 confirm 事件</span></h2>
      <div className="var-row">
        <label>页 <input value={pages} onChange={(e) => setPages(e.target.value)} size={18} title="dev_set | all | 4-56,60" /></label>
        <button onClick={load}>载入</button>
        <span className="muted">{stat}</span>
      </div>
      {staleMsg && (
        <div className="muted vg-stale">
          {staleMsg}
          {stalePagesRef.current.length > 0 && (
            <>
              <button disabled={resyncing} onClick={resync} style={{ marginLeft: '.4rem' }}>
                {resyncing ? '重跑中…' : `重跑这 ${stalePagesRef.current.length} 页同步`}
              </button>
              <span className="mono" style={{ marginLeft: '.4rem' }}>p{stalePagesRef.current.join(' p')}</span>
            </>
          )}
        </div>
      )}
      <div className="vg_groups">
        {mainList.length ? mainList.map(([gr, k]) => groupBtn(gr, k)) : (data ? <span className="muted">这些页里没有待审或多形的组</span> : null)}
        {restList.length > 0 && (
          <details className="vgrest">
            <summary className="muted">其余 {restList.length} 组（这些页里只刻了一种形）</summary>
            {restList.map(([gr, k]) => groupBtn(gr, k))}
          </details>
        )}
      </div>
      {g && (
        <>
          <p className="muted var-help">
            红虚框 = 义定形未定（待审）。<b>单击 = 选中</b>（蓝框），选中后才好按键；
            <b>双击 / 空格 / ←→</b> = 挪列改形。提交时每格记 shape（所在列）+ reading（整理本字），两者不同即一次转换。
            选中后可按：<b>O</b> 组外（两个形都不是——扔进下面那栏再填字） ·
            <b>N</b> 非字 · <b>T</b> 字形不完整 · <b>C</b> 有噪声——后三个是"这块图不能用，不是认错字"，
            提交后写进金标与排除名单，这一格<b>以后不进库也不再出卡</b>。
            "照准全部"把已自动放行的也确认一遍——那就是字形保真率的抽审。
          </p>
          <div className="vgrid" style={{ gridTemplateColumns: `repeat(${cols.length},minmax(0,1fr))` }}>
            {cols.map((c) => {
              const f = g.forms[c] || { book: { products: 0, db: 0, align: 0 }, ref: 0 }
              const b = f.book
              const carved = Math.max(0, (b.products || 0) + (b.db || 0) - (b.align || 0))
              return (
                <div className="vcol" key={c}>
                  <div className="vhead">
                    <span className="vgl">{c}</span>
                    <span className="muted">刻 {carved}{b.human ? `·人${b.human}` : ''} · 整理本 {f.ref || 0}{c === g.reading_default ? ' · 文意' : ''}{c === g.preferred ? ' · 本书惯用' : ''}</span>
                  </div>
                  <div className="vtiles">
                    {(byCol[c] || []).map((t) => {
                      const s = tileState.current[t.id]
                      const cls = ['vtile', t.pending ? 'pending' : '', t.stale ? 'stale' : '', t.audit ? 'audit' : '',
                        s.changed ? 'moved' : '', s.mark ? 'marked' : '', t.human ? 'hum' : '', selRef.current === t.id ? 'sel' : '']
                        .filter(Boolean).join(' ')
                      const tip = `${t.id} · ${t.pending ? '待审' : (t.stale ? `你已裁「${t.human}」，产物待重跑` : `自动 ${t.channel || ''}`)}`
                      const badge = s.mark ? <b>{{ non: 'N', truncated: 'T', contaminated: 'C' }[s.mark]}</b> : (t.human ? <i>{t.human}</i> : null)
                      return (
                        <div key={t.id} className={cls} title={tip} tabIndex={0} data-id={t.id}
                             onClick={(ev) => { selRef.current = t.id; ev.currentTarget.focus(); bump() }}
                             onDoubleClick={() => moveCol(g, t.id, 1)}
                             onKeyDown={(ev) => onTileKeyDown(g, t, ev)}>
                          <img src={t.patch} alt={t.id} />{badge}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
          <div className={`vother${others.length ? '' : ' empty'}`}>
            <div className="vhead"><span className="muted">组外（不是这一组的任何一个形；选中格子按 <b>O</b> 扔进来，再填它到底是什么字；填错了在框里按 <b>Esc</b> 放回）</span></div>
            <div className="vtiles">
              {others.map((t) => {
                const s = tileState.current[t.id]
                return (
                  <div className="votile" key={t.id}>
                    <div className="vtile marked" title={`${t.id}\n再按 O 放回组内`} tabIndex={0}>
                      <img src={t.patch} alt={t.id} loading="lazy" /><b>O</b>
                    </div>
                    <input className="voin" value={s.otherChar || ''} placeholder="是什么字" size={3}
                           title="填图上实际刻的字；留空则提交时跳过这一格。按 Esc 放回组内"
                           onChange={(e) => { s.otherChar = e.target.value.trim(); s.changed = true }}
                           onKeyDown={(ev) => {
                             if (ev.key !== 'Escape') return
                             ev.preventDefault()
                             s.other = false; s.otherChar = ''; s.changed = s.col !== s.orig
                             selRef.current = t.id
                             bump()
                           }} />
                  </div>
                )
              })}
            </div>
          </div>
          <div className="var-row">
            <button onClick={() => send(false)}>提交待审与改动</button>
            <button onClick={() => send(true)}>照准全部（含已自动放行）</button>
            <span className="muted">{msg}</span>
          </div>
        </>
      )}
    </div>
  )
}
