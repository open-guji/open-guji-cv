import { useEffect, useState } from 'react'
import { fetchLibSpot, libPatchUrl, postLibAudit, PROV_LABEL } from '../../api/glyphlib'
import type { SpotItem, SpotResult } from '../../api/glyphlib'

// 抽检（overview#110，2026-09-27）：按来路（缺省 auto = 机器高可信刻例）随机抽 N 条，
// 逐条判对错。**不另造协议**：裁决走 H 的体检接口 `/api/glyphlib/audit/decide`
// （glyph_audit 事件，key = spot:<实例>）——对 = ok（只记账）、错→改字 = relabel、
// 错→撤库 = evict。样本 = seed 固定的随机抽样，刷新不换；撤库的会从池里消失，
// 所以错率按服务端的累计账（tally）报，不按这一屏。
const V_LABEL: Record<string, string> = { ok: '对', relabel: '错·改字', evict: '错·撤库' }

export function LibSpotcheckPanel({ isAdmin, onPick }: { isAdmin: boolean; onPick: (c: string) => void }) {
  const [prov, setProv] = useState('auto')
  const [batch, setBatch] = useState('')
  const [n, setN] = useState(100)
  const [seed, setSeed] = useState(0)
  const [r, setR] = useState<SpotResult | null>(null)
  const [msg, setMsg] = useState('')
  const [done, setDone] = useState<Record<string, { v: string; char?: string }>>({})
  const [busy, setBusy] = useState('')
  const [fix, setFix] = useState<Record<string, string>>({})

  async function load() {
    setMsg('载入中…')
    try {
      const d = await fetchLibSpot(prov, batch, n, seed)
      setR(d); setDone({}); setMsg('')
    } catch (e) { setMsg('失败：' + (e as Error).message) }
  }
  useEffect(() => { load() }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  async function decide(it: SpotItem, v: 'ok' | 'relabel' | 'evict', char?: string) {
    if (v === 'relabel' && !char) { setMsg('改字要先在输入框里填正确的字'); return }
    setBusy(it.key)
    try {
      const res = await postLibAudit({
        key: it.key, instance_id: it.instance_id, v, char_self: it.char,
        ...(v === 'evict' ? { target: it.instance_id } : {}), ...(v === 'relabel' ? { char } : {}),
        flags: ['spotcheck', `prov:${it.provenance}`],
      })
      if (!res.ok) setMsg('写入失败：' + (res.error || res.consume_error || ''))
      else setDone((p) => ({ ...p, [it.key]: { v, char } }))
    } catch (e) { setMsg('写入失败：' + (e as Error).message) } finally { setBusy('') }
  }

  const items = r?.items ?? []
  const stateOf = (it: SpotItem) => done[it.key] ?? it.decision ?? null
  const nJudged = items.filter((it) => stateOf(it)).length
  const nWrong = items.filter((it) => { const s = stateOf(it); return s && s.v !== 'ok' }).length
  const t = r?.tally ?? {}
  const tAll = Object.values(t).reduce((a, b) => a + b, 0)
  const tWrong = tAll - (t.ok ?? 0)

  return (
    <div>
      <div className="card">
        <h3>抽检 <span className="muted">按来路随机抽刻例，逐条判这个字定得对不对</span></h3>
        <div className="rv-toolbar">
          <label className="muted">来路
            <select value={prov} onChange={(e) => setProv(e.target.value)}>
              {['auto', 'human', 'align', 'match', 'context'].map((p) => <option key={p} value={p}>{p} · {PROV_LABEL[p] ?? '机器高可信'}</option>)}
            </select>
          </label>
          <label className="muted" title="只抽证据里 batch 等于它的（空 = 全部）">批次
            <select value={batch} onChange={(e) => setBatch(e.target.value)}>
              <option value="">全部</option>
              {Object.entries(r?.batches ?? {}).map(([b, k]) => <option key={b} value={b}>{b || '（无批次）'} ×{k}</option>)}
            </select>
          </label>
          <label className="muted">条数 <input size={4} value={n} onChange={(e) => setN(+e.target.value || 100)} /></label>
          <label className="muted" title="同一 seed 抽到同一批；换 seed 换一批">seed <input size={4} value={seed} onChange={(e) => setSeed(+e.target.value || 0)} /></label>
          <button onClick={load}>抽样</button>
          <span className="muted">{msg}</span>
        </div>
        {r && (
          <div className="muted">
            池里 {r.n_pool} 条，本屏 {items.length} 条 · 已判 {nJudged}，判错 {nWrong}
            {nJudged ? `（本屏错率 ${(100 * nWrong / nJudged).toFixed(1)}%）` : ''}
            {' · '}累计抽检 {tAll} 条，错 {tWrong}{tAll ? `（${(100 * tWrong / tAll).toFixed(1)}%）` : ''}
            {!isAdmin && ' · 只有管理员能落裁决'}
          </div>
        )}
      </div>
      <div className="spot-grid">
        {items.map((it) => {
          const s = stateOf(it)
          return (
            <div key={it.key} className={`spot-card${s ? (s.v === 'ok' ? ' ok' : ' bad') : ''}`}>
              <img src={libPatchUrl(it.instance_id)} alt={it.instance_id} />
              <div className="spot-char" title="库里定的字">{it.char}</div>
              <div className="muted spot-id">
                <a href="#" onClick={(e) => { e.preventDefault(); onPick(it.char) }}>{it.instance_id}</a>
                {it.evidence.channel && ` · ${it.evidence.channel}`}{it.evidence.verdict && `/${it.evidence.verdict}`}
                {it.evidence.cov != null && ` cov ${it.evidence.cov}`}
              </div>
              {s ? (
                <div className="spot-done">{V_LABEL[s.v] ?? s.v}{s.char ? `「${s.char}」` : ''}</div>
              ) : isAdmin && (
                <div className="spot-btns">
                  <button disabled={!!busy} onClick={() => decide(it, 'ok')}>对</button>
                  <input size={2} placeholder="正字" value={fix[it.key] ?? ''}
                         onChange={(e) => setFix((p) => ({ ...p, [it.key]: e.target.value.trim() }))} />
                  <button disabled={!!busy} onClick={() => decide(it, 'relabel', fix[it.key])}
                          title="定错了、能认出是什么字：按正字重进库（人裁身份）">错·改字</button>
                  <button disabled={!!busy} onClick={() => decide(it, 'evict')}
                          title="定错了、认不出或不是字：撤出库">错·撤库</button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
