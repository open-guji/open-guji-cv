import { useEffect, useState } from 'react'
import { fetchLibChar, FID_LABEL, libFontUrl, libPatchUrl, postLibAudit, PROV_LABEL, PROV_ORDER,
  type LibCharDetail as Detail, type LibExemplar } from '../../api/glyphlib'
import { IdsPicker, type IdsPick } from './IdsPicker'

// 单字页：本书全部刻例（按来路分组）＋ 字体 ＋ 兄弟工作区同字。
// 点刻例可多选，给选中的（没选就给全部未评的）标一致程度（字形库 04）。
export function LibCharDetail({ char, onPick }: { char: string; onPick: (c: string) => void }) {
  const [d, setD] = useState<Detail | null>(null)
  const [err, setErr] = useState('')
  const [q, setQ] = useState(char)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [tick, setTick] = useState(0)
  const [picking, setPicking] = useState(false)
  // 换字时页面用 key={char} 重挂本组件，状态自然清空，这里只管取数
  useEffect(() => {
    if (char) fetchLibChar(char).then(setD).catch((e) => setErr((e as Error).message))
  }, [char, tick])

  const go = (e: React.FormEvent) => { e.preventDefault(); const c = [...q.trim()][0]; if (c) onPick(c) }
  const groups = d ? PROV_ORDER.map((k) => [k, d.exemplars.filter((x) => x.provenance === k)] as const).filter(([, xs]) => xs.length) : []
  const toggle = (id: string) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })

  const targetsNow = () => d ? (sel.size ? [...sel] : d.exemplars.filter((x) => !x.fidelity).map((x) => x.instance_id)) : []

  async function mark(fid: string | null, ids?: string, force?: boolean) {
    if (!d) return
    const targets = targetsNow()
    if (!targets.length) { alert('没有选中的、也没有未评的刻例'); return }
    const r = await postLibAudit({ key: `fid:${d.char}:${Date.now()}`, instance_id: targets[0], v: 'fidelity',
      fidelity: fid, ids, targets, force })
    if (!r.ok) { alert(r.error || r.consume_error || '失败'); return }
    setSel(new Set()); setPicking(false); setTick((t) => t + 1)
  }

  // 反查面板的结果：改字（逐例 relabel）或标最近似 / 无码
  async function onIdsPick(p: IdsPick) {
    if (!d) return
    if (p.kind === 'fidelity') { await mark(p.fidelity, p.ids, p.force); return }
    const targets = targetsNow()
    if (!targets.length || !confirm(`把 ${targets.length} 例从「${d.char}」改成「${p.char}」？`)) return
    for (const t of targets) {
      const r = await postLibAudit({ key: `relabel:${t}:${Date.now()}`, instance_id: t, v: 'relabel', char: p.char })
      if (!r.ok) { alert(r.error || r.consume_error || '失败'); break }
    }
    setSel(new Set()); setPicking(false); setTick((t) => t + 1)
  }

  return (
    <div>
      <form className="pv-toolbar" onSubmit={go}>
        <label className="muted">字 <input type="text" value={q} size={4} onChange={(e) => setQ(e.target.value)} /></label>
        <button type="submit">看</button>
      </form>
      {err && <p className="error">{err}</p>}
      {!char && <p className="muted">从字表点一个字，或在上面输入。</p>}
      {d && (
        <>
          <div className="gl-head">
            <span className="gl-big">{d.char}</span>
            <span className="mono">U+{(d.cp ?? 0).toString(16).toUpperCase()}</span>
            {d.ids && <span className="mono muted" title="通行结构（ids_lv1）">{d.ids}</span>}
            <span>{d.exemplars.length} 例</span>
            {d.heads.map((h) => (
              <span key={h.edition} className="muted">[{h.edition}] {h.status} · 读 {h.semantic ?? '—'}</span>
            ))}
          </div>
          {d.exemplars.length > 0 && (
            <div className="gl-actions gl-fid-bar">
              <span className="muted">一致程度 → {sel.size ? `选中 ${sel.size} 例` : '全部未评'}：</span>
              <button onClick={() => mark('exact')}>完全一致</button>
              <button onClick={() => setPicking(true)} title="写实际结构，先在 Unicode 里反查">最近似码位 / 无码…</button>
              <button onClick={() => mark(null)} disabled={!sel.size} title="撤销选中刻例的标注">撤销</button>
              {sel.size > 0 && <button onClick={() => setSel(new Set())}>清选</button>}
            </div>
          )}
          {picking && <IdsPicker initial={d.ids ?? ''} current={d.char} onPick={onIdsPick} onCancel={() => setPicking(false)} />}
          {d.exemplars.length === 0 && <p className="muted">本书库里没有这个字。</p>}
          {groups.map(([k, xs]) => (
            <div key={k} className="card">
              <h3 className="gl-h3"><i className={`gl-dot gl-p-${k}`} />{PROV_LABEL[k] ?? k} <span className="muted">{xs.length}</span></h3>
              <Tiles xs={xs} sel={sel} onToggle={toggle} />
            </div>
          ))}
          <div className="card">
            <h3 className="gl-h3">对照</h3>
            <div className="gl-row"><span className="gl-row-label mono">{d.fonts[0]?.edition ?? '字体'}</span>
              <img className="gl-img" src={libFontUrl(d.char)} alt="字体"
                onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }} /></div>
            {d.others.map((o) => (
              <div key={o.ws} className="gl-row"><span className="gl-row-label">{o.ws}<br /><span className="muted">{o.n} 例</span></span>
                <Tiles xs={o.exemplars} ws={o.ws} /></div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function Tiles({ xs, ws, sel, onToggle }: {
  xs: LibExemplar[]; ws?: string; sel?: Set<string>; onToggle?: (id: string) => void
}) {
  return (
    <div className="gl-tiles">
      {xs.map((x) => (
        <figure key={x.instance_id}
          className={`gl-tile${x.duplicate ? ' gl-dup' : ''}${sel?.has(x.instance_id) ? ' gl-sel' : ''}${onToggle ? ' gl-click' : ''}`}
          onClick={onToggle ? () => onToggle(x.instance_id) : undefined}
          title={`${x.instance_id}\n来路 ${x.provenance_raw ?? '—'}　读 ${x.semantic ?? '—'}` +
            `${x.fidelity ? `\n一致程度 ${FID_LABEL[x.fidelity] ?? x.fidelity}${x.ids ? ' ' + x.ids : ''}` : ''}` +
            `\n${x.admitted_at ?? ''}${x.event ? '\n' + x.event : ''}`}>
          <img className="gl-img" src={libPatchUrl(x.instance_id, ws)} alt={x.instance_id} loading="lazy" />
          <figcaption className="mono">{x.fidelity && <b className={`gl-fid gl-fid-${x.fidelity}`}>{FID_LABEL[x.fidelity]?.[0]}</b>}
            {x.page}:{x.col}:{x.idx}</figcaption>
        </figure>
      ))}
    </div>
  )
}
