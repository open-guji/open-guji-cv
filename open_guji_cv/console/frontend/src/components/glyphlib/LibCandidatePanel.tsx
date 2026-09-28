import { useEffect, useState } from 'react'
import { libPatchUrl, PROV_LABEL } from '../../api/glyphlib'
import { candPatchSrc, fetchCandList, fetchCandLists, postCandDecision } from '../../api/glyphCandidates'
import type { CandCell, CandList, CandListInfo, CandVerdict } from '../../api/glyphCandidates'
import { BinaryToggleImage } from '../common/BinaryToggleImage'

// 待纳入（overview#176，2026-09-28）：还没进库的候选刻例（工作区 feedback/candidates/*.jsonl），
// 按字分组，每格原图字块旁并排放库里同字的已有刻例，逐格判「收／不收／看不清」。
// 裁决照常落 POST /api/events（kind=admit_candidate）；**这里不写库**，进库由 H 道重放完成。
// 与体检、抽检一样只让管理员落裁决（进库是全书共享状态）。
const V_LABEL: Record<CandVerdict, string> = { admit: '收', reject: '不收', unclear: '看不清' }
const V_TITLE: Record<CandVerdict, string> = {
  admit: '这格就是这个字、图可用：记一条「收」，H 道重放时进库',
  reject: '字不对或图不能用：不进库',
  unclear: '图太糊 / 拿不准：先放着，不进库',
}

function evidenceText(ev: Record<string, unknown>): string {
  const parts: string[] = []
  if (ev.source) parts.push(String(ev.source))
  if (ev.margin != null) parts.push(`margin ${Number(ev.margin).toFixed(2)}`)
  for (const [k, v] of Object.entries(ev)) {
    if (k === 'source' || k === 'margin' || v == null || typeof v === 'object') continue
    parts.push(`${k} ${v}`)
  }
  return parts.join(' · ')
}

export function LibCandidatePanel({ isAdmin, onPick }: { isAdmin: boolean; onPick: (c: string) => void }) {
  const [lists, setLists] = useState<CandListInfo[] | null>(null)
  const [dir, setDir] = useState('')
  const [lid, setLid] = useState('')
  const [d, setD] = useState<CandList | null>(null)
  const [msg, setMsg] = useState('')
  const [onlyTodo, setOnlyTodo] = useState(false)
  const [busy, setBusy] = useState('')
  const [local, setLocal] = useState<Record<string, CandVerdict>>({})

  useEffect(() => {
    fetchCandLists().then((r) => {
      setLists(r.lists); setDir(r.dir)
      if (r.lists[0]) setLid((cur) => cur || r.lists[0].id)
    }).catch((e) => setMsg('失败：' + (e as Error).message))
  }, [])

  useEffect(() => {
    if (!lid) return
    setMsg('载入中…'); setD(null); setLocal({})
    fetchCandList(lid).then((r) => { setD(r); setMsg('') }).catch((e) => setMsg('失败：' + (e as Error).message))
  }, [lid])

  async function decide(c: CandCell, v: CandVerdict) {
    if (!d) return
    setBusy(c.cell_id)
    try {
      const r = await postCandDecision(d, c, v)
      if (!r.appended) setMsg('没写进去（appended=0）')
      else setLocal((p) => ({ ...p, [c.cell_id]: v }))
    } catch (e) { setMsg('写入失败：' + (e as Error).message) } finally { setBusy('') }
  }

  const stateOf = (c: CandCell): CandVerdict | null => local[c.cell_id] ?? c.decision?.v ?? null
  const cells = d?.groups.flatMap((g) => g.cells) ?? []
  const t = { admit: 0, reject: 0, unclear: 0, todo: 0 }
  for (const c of cells) { const s = stateOf(c); if (s) t[s]++; else t.todo++ }

  if (lists && !lists.length) {
    return (
      <div className="card">
        <h3>待纳入 <span className="muted">还没进库的候选刻例</span></h3>
        <p className="muted">这个工作区还没有候选清单。清单放在 <code>{dir}</code>，一行一格的 jsonl
          （<code>cell_id</code>、<code>char</code>、<code>evidence</code>，可选 <code>ref_instances</code>），
          格式见 <code>feedback/candidates.py</code>。</p>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <h3>待纳入 <span className="muted">还没进库的候选刻例：左边是库里同字已有的刻例，右边逐格判收不收</span></h3>
        <div className="rv-toolbar">
          <label className="muted cand-pick">清单
            <select value={lid} onChange={(e) => setLid(e.target.value)}>
              {(lists ?? []).map((l) => (
                <option key={l.id} value={l.id}>{l.title} · {l.n} 格 · 未裁 {l.tally.todo}</option>
              ))}
            </select>
          </label>
          <label className="muted"><input type="checkbox" checked={onlyTodo} onChange={(e) => setOnlyTodo(e.target.checked)} /> 只看未裁</label>
          <span className="muted">{msg}</span>
        </div>
        {d && (
          <div className="muted">
            {cells.length} 格 / {d.groups.length} 字 · 收 {t.admit} · 不收 {t.reject} · 看不清 {t.unclear} · 未裁 {t.todo}
            {' · '}裁决只落事件（批次 <code>{d.batch}</code>），进库由 H 道重放完成
            {!isAdmin && ' · 只有管理员能落裁决'}
          </div>
        )}
        {d && d.problems.length > 0 && (
          <details className="muted"><summary>清单里有 {d.problems.length} 行没读进来</summary>
            <ul className="gl-list">{d.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
          </details>
        )}
      </div>
      {d?.groups.map((g) => {
        const shown = onlyTodo ? g.cells.filter((c) => !stateOf(c)) : g.cells
        if (!shown.length) return null
        return (
          <div key={g.char} className="card cand-group">
            <div className="gl-audit-head">
              <a href="#" className="gl-big-sm" title="打开单字页"
                 onClick={(e) => { e.preventDefault(); onPick(g.char) }}>{g.char}</a>
              <span className="muted">候选 {g.cells.length} 格 · 库里已有 {g.n_lib == null ? '？（本工作区没有库）' : g.n_lib} 例</span>
            </div>
            <div className="cand-row">
              <div className="cand-lib">
                <div className="muted cand-label">库里同字</div>
                {g.lib.length ? (
                  <div className="gl-tiles">
                    {g.lib.map((e) => (
                      <figure key={e.instance_id} className={`gl-tile${e.is_ref ? ' gl-sel' : ''}`}
                              title={`${e.instance_id} · ${PROV_LABEL[e.provenance] ?? e.provenance}${e.is_ref ? ' · 清单点名的对照' : ''}`}>
                        <img className="gl-img cand-lib-img" src={libPatchUrl(e.instance_id)} alt={e.instance_id} loading="lazy" />
                        <figcaption>{PROV_LABEL[e.provenance] ?? e.provenance}</figcaption>
                      </figure>
                    ))}
                    {g.n_lib != null && g.n_lib > g.lib.length && <span className="muted">…另 {g.n_lib - g.lib.length} 例</span>}
                  </div>
                ) : <div className="muted">（库里还没有这个字）</div>}
              </div>
              <div className="cand-cells">
                {shown.map((c) => {
                  const s = stateOf(c)
                  return (
                    <div key={c.cell_id} className={`spot-card cand-card${s ? ` cand-${s}` : ''}`}>
                      <BinaryToggleImage src={candPatchSrc(c)} alt={c.cell_id} />
                      <div className="muted spot-id">{c.cell_id}</div>
                      <div className="muted spot-id">{evidenceText(c.evidence)}</div>
                      {isAdmin ? (
                        <div className="spot-btns">
                          {(['admit', 'reject', 'unclear'] as CandVerdict[]).map((v) => (
                            <button key={v} disabled={!!busy} title={V_TITLE[v]}
                                    className={s === v ? 'active' : ''} onClick={() => decide(c, v)}>{V_LABEL[v]}</button>
                          ))}
                        </div>
                      ) : s && <div className="spot-done">{V_LABEL[s]}</div>}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
