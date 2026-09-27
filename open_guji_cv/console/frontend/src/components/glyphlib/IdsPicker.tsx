import { useEffect, useState } from 'react'
import { fetchIdsLookup, libFontUrl, type IdsHit } from '../../api/glyphlib'

// 标「最近似码位 / 无码」的面板：写刻例的实际结构（IDS），边写边在 Unicode 里反查
// （clustering/ids_lookup.py）。查到同结构的字 = 它其实有码位，应当「改成这个字」；
// 人看过候选、确认都不是，才标最近似 / 无码（带 force）。
export type IdsPick =
  | { kind: 'relabel'; char: string }
  | { kind: 'fidelity'; fidelity: 'nearest' | 'unencoded'; ids: string; force: boolean }

const MATCH_LABEL: Record<string, string> = { exact: '同结构', expanded: '展开后同结构', near: '近似' }
const IDC_BTNS = '⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻'

export function IdsPicker({ initial, current, onPick, onCancel }: {
  initial: string; current: string; onPick: (p: IdsPick) => void; onCancel: () => void
}) {
  const [q, setQ] = useState(initial)
  const [hits, setHits] = useState<IdsHit[]>([])
  const [err, setErr] = useState('')
  const [sure, setSure] = useState(false)
  // 查到的是哪条 IDS 的结果：与输入框不一致 = 还在查（首查要建 10 万字的索引，约 4 秒）
  const [doneFor, setDoneFor] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    const want = q.trim()
    const t = setTimeout(() => {
      if (!want) return
      fetchIdsLookup(want).then((r) => { if (live) { setHits(r.hits); setErr(r.error ?? ''); setDoneFor(want) } })
        .catch((e) => { if (live) { setErr((e as Error).message); setDoneFor(want) } })
    }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [q])
  const loading = !!q.trim() && doneFor !== q.trim()
  const encoded = hits.filter((h) => h.match !== 'near' && h.char !== current)
  const canMark = q.trim() && !loading && !err && (encoded.length === 0 || sure)
  const mark = (fidelity: 'nearest' | 'unencoded') =>
    onPick({ kind: 'fidelity', fidelity, ids: q.trim(), force: encoded.length > 0 })

  return (
    <div className="gl-ids card">
      <div className="pv-toolbar">
        <label className="muted">刻例实际结构（IDS）
          <input type="text" value={q} size={24} onChange={(e) => { setQ(e.target.value); setSure(false) }} autoFocus />
        </label>
        <span className="gl-idc">{[...IDC_BTNS].map((c) => (
          <button key={c} type="button" onClick={() => setQ(q + c)}>{c}</button>))}</span>
        <button type="button" onClick={onCancel}>取消</button>
      </div>
      {err && <p className="error">{err}</p>}
      {encoded.length > 0 && (
        <p className="pb-note pb-note-ochre">这个结构 Unicode 里已有：{encoded.map((h) => h.char).join('、')}。
          多半该「改成这个字」，而不是标最近似。</p>
      )}
      <div className="gl-ids-hits">
        {hits.map((h) => (
          <figure key={h.char} className={`gl-tile gl-ids-hit gl-m-${h.match}`}>
            <img className="gl-img" src={libFontUrl(h.char)} alt={h.char}
              onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }} />
            <figcaption>
              <b>{h.char}</b> <span className="mono">U+{h.cp.toString(16).toUpperCase()}</span><br />
              {MATCH_LABEL[h.match]}{h.match === 'near' ? ` 差${h.diff}` : ''} · {h.block}{h.in_book ? ' · 本书有' : ''}<br />
              <span className="mono muted">{h.ids}</span><br />
              {h.char !== current && <button type="button" onClick={() => onPick({ kind: 'relabel', char: h.char })}>就是它，改字</button>}
            </figcaption>
          </figure>
        ))}
        {loading && <p className="muted">查询中…</p>}
        {!loading && !hits.length && q.trim() && !err && <p className="muted">Unicode（IDS 表 10.2 万字）里查不到相同或近似的结构。</p>}
      </div>
      <div className="gl-actions">
        {encoded.length > 0 && (
          <label className="muted"><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} /> 看过了，上面都不是</label>
        )}
        <button className="primary" disabled={!canMark} onClick={() => mark('nearest')}>标「最近似码位」（仍存「{current}」）</button>
        <button disabled={!canMark} onClick={() => mark('unencoded')}>标「无码」</button>
      </div>
    </div>
  )
}
