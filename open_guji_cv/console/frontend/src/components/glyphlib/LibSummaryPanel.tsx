import { useEffect, useState } from 'react'
import { fetchLibSummary, FID_LABEL, PROV_LABEL, PROV_ORDER, type LibSummary } from '../../api/glyphlib'

// 总账：本书套（全部非字体来源并一套、按格去重）＋ 各来源 ＋ 字体覆盖 ＋ 真源健康 ＋ 兄弟工作区。
export function LibSummaryPanel({ onFilter }: { onFilter: (f: string) => void }) {
  const [s, setS] = useState<LibSummary | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { fetchLibSummary().then(setS).catch((e) => setErr((e as Error).message)) }, [])
  if (err) return <p className="error">{err}</p>
  if (!s) return <p className="muted">读取中…</p>
  const b = s.book
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`
  return (
    <div>
      {!s.store.ok && <p className="pb-note pb-note-ochre">真源：{s.store.message}</p>}
      {s.head_anomalies > 0 && (
        <p className="pb-note pb-note-ochre">字头脏数据 {s.head_anomalies} 行（semantic 非汉字 / 码位缺失），`glyph-db repair --apply` 可修</p>
      )}
      <div className="pb-tiles">
        <Tile label="字种" value={b.chars} />
        <Tile label="刻例（格）" value={b.cells} />
        <Tile label="人裁占比" value={pct(b.human_share)} hint={`${b.provenance.human ?? 0} 例`} />
        <Tile label="有人裁的字" value={b.chars_with_human} hint={`占字种 ${pct(b.chars_with_human / Math.max(1, b.chars))}`} />
        <Tile label="单例字" value={b.singleton_chars} hint="全书只一个刻例，体检最弱" onClick={() => onFilter('single')} />
        {b.shadow_duplicates > 0 && <Tile label="同格两份" value={b.shadow_duplicates} ochre />}
      </div>

      <div className="card">
        <h3 className="gl-h3">来路</h3>
        <div className="gl-bar">
          {PROV_ORDER.filter((k) => b.provenance[k]).map((k) => (
            <span key={k} className={`gl-bar-seg gl-p-${k}`} style={{ flex: b.provenance[k] }}
              title={`${PROV_LABEL[k] ?? k} ${b.provenance[k]}`} />
          ))}
        </div>
        <div className="counts">
          {PROV_ORDER.filter((k) => b.provenance[k]).map((k) => (
            <span key={k}><i className={`gl-dot gl-p-${k}`} />{PROV_LABEL[k] ?? k} {b.provenance[k].toLocaleString()}
              <span className="muted">（{pct(b.provenance[k] / b.exemplars)}）</span></span>
          ))}
        </div>
        <p className="muted gl-note">人裁是新 Step7「库里有完全同形且已定字的实例」这条铁证的来源；
          上下文（Step6 n-gram）通道会背整理本，是体检优先对象。</p>
      </div>

      <div className="card">
        <h3 className="gl-h3">一致程度</h3>
        <div className="counts">
          {['exact', 'variant_encoded', 'nearest', 'unencoded', 'unrated'].filter((k) => s.fidelity?.[k]).map((k) => (
            <span key={k}>{FID_LABEL[k]} {s.fidelity[k].toLocaleString()}</span>
          ))}
        </div>
        <p className="muted gl-note">刻例与所定码位的字形一致到什么程度。「有码异体」= 刻的形与读法不同（卽 读 即），自动算；
          其余要人在单字页或体检卡上标。「最近似码位」「无码」附 IDS 记刻例实际结构。</p>
      </div>

      <div className="card">
        <h3 className="gl-h3">来源（库里的 edition）</h3>
        <table className="pb-table">
          <thead><tr><th className="pb-left">edition</th><th>类型</th><th>字头行</th><th>stable</th><th>刻例</th></tr></thead>
          <tbody>
            {s.editions.map((e) => (
              <tr key={e.edition}>
                <td className="pb-left mono">{e.edition}</td>
                <td>{e.kind === 'font' ? '字体' : '刻例'}</td>
                <td>{e.chars.toLocaleString()}</td><td>{e.stable.toLocaleString()}</td><td>{e.exemplars.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted gl-note">人裁一律落 <span className="mono">v2</span>（实例 id 命名空间，不是另一套书），
          上面的总数已把本书各刻例来源并成一套；{b.chars_split_across_editions} 个字在两个来源里各有字头行。</p>
      </div>

      <div className="card">
        <h3 className="gl-h3">对照</h3>
        <ul className="gl-list">
          {Object.entries(s.fonts).map(([ed, f]) => (
            <li key={ed}><span className="mono">{ed}</span> {f.chars.toLocaleString()} 字；本书有
              <a href="#" onClick={(ev) => { ev.preventDefault(); onFilter('nofont') }}> {f.book_chars_not_in_font} 字不在这套字体里</a></li>
          ))}
          {Object.keys(s.fonts).length === 0 && <li className="muted">库里没有导入字体域（`glyph-db import-font`）</li>}
          {s.others.map((o) => (
            <li key={o.ws}>{o.name}（<span className="mono">{o.ws}</span>）
              {o.error ? <span className="error"> 读不出：{o.error}</span>
                : <> {o.chars?.toLocaleString()} 字，与本书
                  <a href="#" onClick={(ev) => { ev.preventDefault(); onFilter(`shared:${o.ws}`) }}> 共有 {o.common?.toLocaleString()} 字</a></>}
            </li>
          ))}
        </ul>
        <p className="muted">真源 store {s.store.store_exemplars ?? '—'} / 库 {s.store.db_exemplars} 例{s.store.ok ? '，一致' : ''}</p>
      </div>
    </div>
  )
}

function Tile({ label, value, hint, ochre, onClick }: {
  label: string; value: number | string; hint?: string; ochre?: boolean; onClick?: () => void
}) {
  return (
    <div className={`pb-tile${onClick ? ' gl-click' : ''}`} onClick={onClick}>
      <div className="pb-tile-label">{label}</div>
      <div className={`pb-tile-value${ochre ? ' pb-ochre' : ''}`}>{typeof value === 'number' ? value.toLocaleString() : value}</div>
      {hint && <div className="muted">{hint}</div>}
    </div>
  )
}
