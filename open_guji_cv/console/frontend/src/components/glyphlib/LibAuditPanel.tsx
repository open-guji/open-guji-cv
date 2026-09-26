import { useEffect, useMemo, useState } from 'react'

// 一批只渲染这么多卡（每卡六张图）：四庫 435 张一次铺开，浏览器卡死（用户 2026-09-26）
const BATCH = 30
import { IdsPicker } from './IdsPicker'
import { fetchLibAudit, FONT_NAME, libFontUrl, libPatchUrl, postLibAudit, PROV_LABEL,
  type AuditDecision, type AuditFinding, type AuditResult } from '../../api/glyphlib'

// 体检：`glyph-db selfcheck` 标出的可疑刻例，一张卡一个。本例与它的同字最近、
// 本书里最像的别的字、他书里最像的别的字、字体（本字 / 最像的别的字）并排。
// 裁决走 glyph_audit 事件（feedback/glyph_audit.py）：没问题 / 形近·异体 / 撤库 / 改字。
export function LibAuditPanel({ onPick }: { onPick: (c: string) => void }) {
  const [r, setR] = useState<AuditResult | null>(null)
  const [err, setErr] = useState('')
  const [flag, setFlag] = useState('')
  const [done, setDone] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [picking, setPicking] = useState('')
  const [skipped, setSkipped] = useState<Set<string>>(new Set())   // 翻过去没裁的，本轮不再出
  const [view, setView] = useState<string[] | null>(null)          // 当前这一批的卡（key）
  useEffect(() => { fetchLibAudit().then(setR).catch((e) => setErr((e as Error).message)) }, [])

  const shown = useMemo(() => (r?.findings ?? []).filter((f) => !flag || f.flags.includes(flag)
    || (flag === 'human_conflict' && f.human_conflict) || (flag === 'context' && f.provenance === 'context')), [r, flag])

  // 下一批：跳过当前批里没裁的，从剩下（未裁、未跳过）的里再取 BATCH 张
  const takeBatch = (skip: Set<string>) =>
    shown.filter((f) => !done[f.key] && !skip.has(f.key)).slice(0, BATCH).map((f) => f.key)
  const batchKeys = view ?? takeBatch(skipped)
  const byKey = new Map(shown.map((f) => [f.key, f]))
  const batch = batchKeys.map((k) => byKey.get(k)).filter((f): f is AuditFinding => !!f)
  const left = shown.filter((f) => !done[f.key] && !skipped.has(f.key) && !batchKeys.includes(f.key)).length
  const nBatchDone = batch.filter((f) => done[f.key]).length
  function nextBatch() {
    const skip = new Set(skipped)
    batch.forEach((f) => { if (!done[f.key]) skip.add(f.key) })
    setSkipped(skip)
    setView(takeBatch(skip))
    window.scrollTo({ top: 0 })
  }
  function restart() { setSkipped(new Set()); setView(null) }

  async function decide(f: AuditFinding, d: Omit<AuditDecision, 'key' | 'instance_id'>) {
    setBusy(f.key)
    try {
      const res = await postLibAudit({ key: f.key, instance_id: f.instance_id, flags: f.flags, char_self: f.char,
        peer: f.rival_peer ?? f.xrival_peer, peer_char: f.rival_char ?? f.xrival_char ?? f.font_char, ...d })
      if (!res.ok) { alert(res.error || res.consume_error || '失败'); return }
      setDone((m) => ({ ...m, [f.key]: label(d) }))
    } catch (e) { alert((e as Error).message) } finally { setBusy('') }
  }

  if (err) return <p className="error">{err}</p>
  if (!r) return <p className="muted">读取中…</p>
  if (!r.meta.n_checked) return (
    <div className="card"><p>还没跑过体检。在工作区上跑：</p>
      <pre className="mono">python -m open_guji_cv glyph-db selfcheck</pre>
      <p className="muted">结果落 <span className="mono">{r.out}</span>。北行约 15 分钟、四庫约 1 小时（两核）。</p></div>
  )
  const fc = r.meta.flag_counts ?? {}
  return (
    <div>
      <div className="pv-toolbar">
        <span className="muted">体检于 {r.meta.created_at}，查 {r.meta.n_checked?.toLocaleString()} 例，标 {r.meta.n_flagged} 例；
          已裁 {r.n_decided + Object.keys(done).length}，参照：{(r.meta.others ?? []).join('、') || '仅本书'}</span>
        <label className="muted">只看
          <select value={flag} onChange={(e) => { setFlag(e.target.value); restart() }}>
            <option value="">全部 {r.findings.length}</option>
            {Object.entries(r.flag_labels).map(([k, t]) => <option key={k} value={k}>{t} {fc[k] ?? 0}</option>)}
            <option value="human_conflict">人裁 × 人裁冲突</option>
            <option value="context">上下文放行的</option>
          </select>
        </label>
      </div>
      {r.meta.fonts && (
        <details className="card gl-fonts">
          <summary>本书刻例与各字体的相似度（本字，弹性覆盖率）</summary>
          <table className="pb-table">
            <thead><tr><th className="pb-left">字体</th><th>中位</th><th>P10</th><th>最像它的刻例</th></tr></thead>
            <tbody>
              {Object.entries(r.meta.fonts).sort((a, b) => b[1].median - a[1].median).map(([k, v]) => (
                <tr key={k}><td className="pb-left">{FONT_NAME[k] ?? k}</td><td>{v.median.toFixed(3)}</td>
                  <td>{v.p10.toFixed(3)}</td><td>{v.best_for.toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted gl-note">与各字体都不像（按字中位 &lt;0.80）的字 {(r.meta.chars_font_far ?? []).length} 个：
            {(r.meta.chars_font_far ?? []).slice(0, 60).map((c) => (
              <a key={c} href="#" onClick={(e) => { e.preventDefault(); onPick(c) }}> {c}</a>))}</p>
        </details>
      )}
      <div className="pv-toolbar gl-batchbar">
        <span>本批 {batch.length} 张，已裁 {nBatchDone}；后面还有 {left} 张{skipped.size ? `，跳过 ${skipped.size} 张` : ''}</span>
        <button className={nBatchDone === batch.length && left ? 'primary' : ''} disabled={!left} onClick={nextBatch}>下一批 {BATCH}</button>
        {skipped.size > 0 && <button onClick={restart}>回头看跳过的</button>}
      </div>
      {batch.map((f) => (
        <div key={f.key} className={`card gl-audit${done[f.key] ? ' gl-done' : ''}`}>
          <div className="gl-audit-head">
            <a href="#" className="gl-big-sm" onClick={(e) => { e.preventDefault(); onPick(f.char) }}>{f.char}</a>
            <span className="mono muted">{f.instance_id}</span>
            <span className="muted">{PROV_LABEL[f.provenance] ?? f.provenance}</span>
            {f.flags.map((k) => <span key={k} className="gl-tag">{r.flag_labels[k] ?? k}</span>)}
            {f.human_conflict && <span className="gl-tag gl-tag-hot">人裁互撞</span>}
            <span className="muted">分 {f.score}</span>
            {done[f.key] && <b className="gl-done-mark">{done[f.key]}</b>}
          </div>
          <div className="gl-tiles">
            <Fig src={libPatchUrl(f.instance_id)} cap="本例" strong />
            {f.same_peer && <Fig src={libPatchUrl(f.same_peer, f.same_peer_ws || undefined)}
              cap={`同字${f.same_peer_ws ? '·他书' : ''} ${f.best_same.toFixed(2)}`} />}
            {f.rival_peer && <Fig src={libPatchUrl(f.rival_peer)} cap={`本书「${f.rival_char}」${f.rival.toFixed(2)}`} />}
            {f.xrival_peer && <Fig src={libPatchUrl(f.xrival_peer, f.xrival_ws)} cap={`${f.xrival_ws}「${f.xrival_char}」${f.xrival.toFixed(2)}`} />}
            {(() => {
              const by = f.font_own_by ?? {}
              const best = Object.keys(by).sort((a, b) => by[b] - by[a])[0]
              const tip = Object.entries(by).map(([k, v]) => `${FONT_NAME[k] ?? k} ${v.toFixed(2)}`).join('\n')
              return <span title={tip}><Fig src={libFontUrl(f.char, best)}
                cap={`${best ? FONT_NAME[best] ?? best : '字体'}本字 ${f.font_own == null ? '—' : f.font_own.toFixed(2)}`} /></span>
            })()}
            {f.font_char && <Fig src={libFontUrl(f.font_char)} cap={`字体「${f.font_char}」${f.font_best.toFixed(2)}`} />}
          </div>
          {!done[f.key] && (
            <div className="gl-actions">
              <button disabled={!!busy} onClick={() => decide(f, { v: 'ok' })}>没问题</button>
              <button disabled={!!busy} onClick={() => decide(f, { v: 'near_form' })}
                title="两个都没标错，只是形近或异体">形近·异体</button>
              <button disabled={!!busy} onClick={() => decide(f, { v: 'evict', target: f.instance_id })}
                title="本例撤出字形库（图坏 / 切坏 / 认不准）">撤本例</button>
              {f.rival_peer && <button disabled={!!busy} onClick={() => decide(f, { v: 'evict', target: f.rival_peer! })}
                title="本书里那个对手标错了，撤它">撤对手「{f.rival_char}」</button>}
              {[f.rival_char, f.xrival_char, f.font_char].filter((c, i, a) => c && a.indexOf(c) === i).map((c) => (
                <button key={c} disabled={!!busy} onClick={() => decide(f, { v: 'relabel', char: c! })}>改成「{c}」</button>
              ))}
              <button disabled={!!busy} onClick={() => {
                const c = [...(prompt('本例其实是哪个字？') ?? '').trim()][0]
                if (c) decide(f, { v: 'relabel', char: c })
              }}>改成…</button>
              <span className="gl-sep" />
              <button disabled={!!busy} onClick={() => decide(f, { v: 'fidelity', fidelity: 'exact' })}
                title="字没标错，且刻的就是这个码位的通行字形">完全一致</button>
              <button disabled={!!busy} onClick={() => setPicking(f.key)}
                title="写实际结构，先在 Unicode 里反查">最近似码位 / 无码…</button>
            </div>
          )}
          {!done[f.key] && picking === f.key && (
            <IdsPicker initial="" current={f.char} onCancel={() => setPicking('')}
              onPick={(p) => { setPicking(''); if (p.kind === 'relabel') decide(f, { v: 'relabel', char: p.char })
                else decide(f, { v: 'fidelity', fidelity: p.fidelity, ids: p.ids, force: p.force }) }} />
          )}
        </div>
      ))}
      {batch.length === 0 && <p className="muted">这一类没有待裁的卡。</p>}
      {batch.length > 0 && (
        <div className="pv-toolbar gl-batchbar">
          <span className="muted">本批已裁 {nBatchDone} / {batch.length}</span>
          <button className={nBatchDone === batch.length && left ? 'primary' : ''} disabled={!left} onClick={nextBatch}>下一批 {BATCH}（跳过本批没裁的）</button>
        </div>
      )}
      <p className="muted gl-note">撤库、改字改的是 glyph.db；裁完在工作区跑 <span className="mono">glyph-db export</span> 把真源带进 git（总账页会提示漂移）。</p>
    </div>
  )
}

function label(d: Omit<AuditDecision, 'key' | 'instance_id'>) {
  if (d.v === 'fidelity') return d.fidelity === 'exact' ? '完全一致' : `${d.fidelity === 'nearest' ? '最近似' : '无码'} ${d.ids}`
  return d.v === 'ok' ? '没问题' : d.v === 'near_form' ? '形近·异体' : d.v === 'evict' ? '已撤' : `改成 ${d.char}`
}

function Fig({ src, cap, strong }: { src: string; cap: string; strong?: boolean }) {
  return (
    <figure className="gl-tile gl-audit-fig">
      <img className={`gl-img gl-img-lg${strong ? ' gl-img-self' : ''}`} src={src} alt={cap} loading="lazy"
        onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }} />
      <figcaption>{cap}</figcaption>
    </figure>
  )
}
