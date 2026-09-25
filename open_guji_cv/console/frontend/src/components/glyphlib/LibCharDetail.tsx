import { useEffect, useState } from 'react'
import { fetchLibChar, libFontUrl, libPatchUrl, PROV_LABEL, PROV_ORDER, type LibCharDetail as Detail, type LibExemplar } from '../../api/glyphlib'

// 单字页：本书全部刻例（按来路分组）＋ 字体 ＋ 兄弟工作区同字。
// 03 卡（库自检）的人审就落在这一页的形并排上。
export function LibCharDetail({ char, onPick }: { char: string; onPick: (c: string) => void }) {
  const [d, setD] = useState<Detail | null>(null)
  const [err, setErr] = useState('')
  const [q, setQ] = useState(char)
  // 换字时页面用 key={char} 重挂本组件，状态自然清空，这里只管取数
  useEffect(() => {
    if (char) fetchLibChar(char).then(setD).catch((e) => setErr((e as Error).message))
  }, [char])

  const go = (e: React.FormEvent) => { e.preventDefault(); const c = [...q.trim()][0]; if (c) onPick(c) }
  const groups = d ? PROV_ORDER.map((k) => [k, d.exemplars.filter((x) => x.provenance === k)] as const).filter(([, xs]) => xs.length) : []
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
            <span>{d.exemplars.length} 例</span>
            {d.heads.map((h) => (
              <span key={h.edition} className="muted">[{h.edition}] {h.status} · 读 {h.semantic ?? '—'}</span>
            ))}
          </div>
          {d.exemplars.length === 0 && <p className="muted">本书库里没有这个字。</p>}
          {groups.map(([k, xs]) => (
            <div key={k} className="card">
              <h3 className="gl-h3"><i className={`gl-dot gl-p-${k}`} />{PROV_LABEL[k] ?? k} <span className="muted">{xs.length}</span></h3>
              <Tiles xs={xs} />
            </div>
          ))}
          {(
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
          )}
        </>
      )}
    </div>
  )
}

function Tiles({ xs, ws }: { xs: LibExemplar[]; ws?: string }) {
  return (
    <div className="gl-tiles">
      {xs.map((x) => (
        <figure key={x.instance_id} className={`gl-tile${x.duplicate ? ' gl-dup' : ''}`}
          title={`${x.instance_id}\n来路 ${x.provenance_raw ?? '—'}　读 ${x.semantic ?? '—'}\n${x.admitted_at ?? ''}${x.event ? '\n' + x.event : ''}`}>
          <img className="gl-img" src={libPatchUrl(x.instance_id, ws)} alt={x.instance_id} loading="lazy" />
          <figcaption className="mono">{x.page}:{x.col}:{x.idx}</figcaption>
        </figure>
      ))}
    </div>
  )
}
