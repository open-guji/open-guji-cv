import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchCandLists } from '../../api/glyphCandidates'
import type { CandListInfo } from '../../api/glyphCandidates'
import { aroundKey, fetchAroundBatch } from '../../api/review'
import type { AroundSlot } from '../../types/review'
import { BinaryToggleImage } from '../common/BinaryToggleImage'
import {
  cellPatchSrc, cellReviewTsvHref, fetchCellReview, postCellDecision,
} from '../../api/cellReview'
import type { CellDecision, CellReviewCell, CellReviewView, CellVerdict } from '../../api/cellReview'
import './cellReview.css'

// 格级审阅（GUJI-364b，2026-10）：单字特写，逐格判「这格是哪个字」。
// 每格：字块特写 + 前后各 2 字上下文 + 候选字按钮 + 四档裁决（候选／无字／看不出／其他）+ 备注。
// 裁决落 POST /api/events（kind=cell_review，consume=false）；这里不写定字、不进库。
// 快捷键（焦点不在输入框时）：1–9 选第 n 个候选、n 无字、u 看不出、o 其他（聚焦单字输入）、
// ← / → 或 k / j 翻格。手机上按钮可点，快捷键只是加速。

const V_LABEL: Record<CellVerdict, string> = { pick: '候选', none: '无字', unsure: '看不出', other: '其他' }
type Local = Pick<CellDecision, 'verdict' | 'picked' | 'other_char' | 'note'>

function ctxText(s: AroundSlot | undefined): string {
  return s ? (s.text ?? s.char ?? '□') : '□'
}

export function CellReviewPanel() {
  const [lists, setLists] = useState<CandListInfo[] | null>(null)
  const [sp] = useSearchParams()
  // `?list=<清单 id>` 直接载入目标清单；没有才落到下拉框第一项（先载第一项会白打它的字块图请求）
  const [lid, setLid] = useState(() => sp.get('list') ?? '')
  const [imgErr, setImgErr] = useState(false)
  const [view, setView] = useState<CellReviewView | null>(null)
  const [idx, setIdx] = useState(0)
  const [local, setLocal] = useState<Record<string, Local>>({})
  const [around, setAround] = useState<AroundSlot[]>([])
  const [at, setAt] = useState(-1)
  const [other, setOther] = useState('')
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const cells = useMemo(() => view?.cells ?? [], [view])
  const cur: CellReviewCell | undefined = cells[idx]
  const decOf = (c: CellReviewCell): Local | null => local[c.cell_id] ?? c.decision ?? null

  useEffect(() => {
    fetchCandLists().then((r) => {
      setLists(r.lists)
      if (r.lists[0]) setLid((cur) => cur || r.lists[0].id)
    }).catch((e) => setMsg('失败：' + (e as Error).message))
  }, [])

  useEffect(() => {
    if (!lid) return
    setMsg('载入中…'); setView(null); setLocal({}); setIdx(0)
    fetchCellReview(lid).then((r) => { setView(r); setMsg('') }).catch((e) => setMsg('失败：' + (e as Error).message))
  }, [lid])

  // 当前格的前后上下文：一次请求，取 at 位置前后各 2 字
  useEffect(() => {
    setAround([]); setAt(-1); setOther(''); setNote(''); setImgErr(false)
    if (!cur) return
    setMsg('')                       // 换格即清掉上一格的提示（如「其他」报错）
    let live = true
    fetchAroundBatch(cur.book, 2, 2, [{ page: cur.page, col: cur.col, slot: cur.slot, sub: cur.sub || '' }])
      .then((r) => {
        if (!live) return
        const ctx = r.around[aroundKey({ page: cur.page, col: cur.col, slot: cur.slot, sub: cur.sub || '' })]
        setAround(ctx?.slots ?? []); setAt(ctx?.at ?? -1)
      })
      .catch(() => { if (live) setMsg('上下文没取到（字块仍可判）') })
    return () => { live = false }
  }, [cur])

  const tally = useMemo(() => {
    const t: Record<CellVerdict | 'todo', number> = { pick: 0, none: 0, unsure: 0, other: 0, todo: 0 }
    for (const c of cells) { const d = decOf(c); if (d) t[d.verdict]++; else t.todo++ }
    return t
  }, [cells, local]) // eslint-disable-line react-hooks/exhaustive-deps

  function go(delta: number) {
    setIdx((i) => Math.min(cells.length - 1, Math.max(0, i + delta)))
  }
  function nextTodo() {
    for (let i = idx + 1; i < cells.length; i++) if (!decOf(cells[i])) { setIdx(i); return }
    go(1)
  }

  async function submit(c: CellReviewCell, choice: { verdict: CellVerdict; picked?: string; other_char?: string }) {
    if (!view) return
    if (choice.verdict === 'pick' && !c.cands.includes(choice.picked ?? '')) { setMsg('候选里没有这个字'); return }
    if (choice.verdict === 'other' && [...(choice.other_char ?? '')].length !== 1) {
      setMsg('其他：只能填一个字（多字请写进备注）'); return
    }
    setBusy(true)
    try {
      const r = await postCellDecision(view, c, { ...choice, note: note.trim() })
      if (!r.appended) { setMsg('没写进去（appended=0）'); return }
      setLocal((p) => ({
        ...p,
        [c.cell_id]: {
          verdict: choice.verdict, picked: choice.picked ?? null,
          other_char: choice.other_char ?? null, note: note.trim(),
        },
      }))
      setMsg('')
      nextTodo()
    } catch (e) {
      setMsg('写入失败：' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (!cur || busy) return
      if (e.key === 'ArrowRight' || e.key === 'j') { go(1); return }
      if (e.key === 'ArrowLeft' || e.key === 'k') { go(-1); return }
      if (e.key === 'n') { void submit(cur, { verdict: 'none' }); return }
      if (e.key === 'u') { void submit(cur, { verdict: 'unsure' }); return }
      if (e.key === 'o') { document.getElementById('cr-other')?.focus(); return }
      const n = Number(e.key)
      if (n >= 1 && n <= 9 && cur.cands[n - 1]) void submit(cur, { verdict: 'pick', picked: cur.cands[n - 1] })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (lists && !lists.length) {
    return <div className="card"><p className="muted">还没有候选清单（feedback/candidates 下没有 jsonl）。</p></div>
  }

  const d = cur ? decOf(cur) : null
  const before = at >= 0 ? around.slice(Math.max(0, at - 2), at) : []
  const after = at >= 0 ? around.slice(at + 1, at + 3) : []

  return (
    <div className="cr">
      <div className="card cr-head">
        <label>候选清单
          <select value={lid} onChange={(e) => setLid(e.target.value)}>
            {(lists ?? []).map((l) => <option key={l.id} value={l.id}>{l.title || l.id}</option>)}
          </select>
        </label>
        {view && (
          <p className="muted">
            共 {cells.length} 格 · 候选 {tally.pick} · 无字 {tally.none} · 看不出 {tally.unsure} · 其他 {tally.other} · 未裁 {tally.todo}
            {' '}<a className="cr-btn" href={cellReviewTsvHref(view.id)} download>下载 TSV</a>
          </p>
        )}
        {msg && <p className="cr-msg">{msg}</p>}
      </div>

      {cur && view && (
        <div className="card cr-cell">
          <div className="cr-title">
            <code>{cur.cell_id}</code>
            <span className="muted"> {idx + 1} / {cells.length}{cur.reason ? ` · ${cur.reason}` : ''}</span>
            {d && <span className="cr-done">已裁：{V_LABEL[d.verdict]}{d.picked ? `「${d.picked}」` : ''}{d.other_char ? `「${d.other_char}」` : ''}</span>}
          </div>

          <div className="cr-stage">
            <div className="cr-ctx">{before.map((s, i) => <span key={`b${i}`}>{ctxText(s)}</span>)}</div>
            <div className="cr-focus">
              {imgErr
                ? <div className="muted">此格没有字块图（本工作区无该格产物）</div>
                : <div onErrorCapture={() => setImgErr(true)}>
                    <BinaryToggleImage src={cellPatchSrc(cur)} alt={cur.cell_id} />
                  </div>}
              <div className="cr-ocr">原读：<strong>{cur.char || '—'}</strong></div>
            </div>
            <div className="cr-ctx">{after.map((s, i) => <span key={`a${i}`}>{ctxText(s)}</span>)}</div>
          </div>

          <div className="cr-choices">
            {cur.cands.map((c, i) => (
              <button key={c} className={`cr-cand${d?.verdict === 'pick' && d.picked === c ? ' on' : ''}`}
                disabled={busy} onClick={() => submit(cur, { verdict: 'pick', picked: c })}
                title={`快捷键 ${i + 1}`}>
                <span className="cr-k">{i + 1}</span>{c}
              </button>
            ))}
            {!cur.cands.length && <span className="muted">这格没有候选字</span>}
          </div>

          <div className="cr-choices">
            <button className={`cr-btn${d?.verdict === 'none' ? ' on' : ''}`} disabled={busy}
              onClick={() => submit(cur, { verdict: 'none' })} title="快捷键 n：这格不是字（残缺、非字形、重影）">无字 <kbd>n</kbd></button>
            <button className={`cr-btn${d?.verdict === 'unsure' ? ' on' : ''}`} disabled={busy}
              onClick={() => submit(cur, { verdict: 'unsure' })} title="快捷键 u：看不出，留给别人或以后再看">看不出 <kbd>u</kbd></button>
            <span className="cr-other">
              <input id="cr-other" className="cr-input" maxLength={4} value={other}
                placeholder="其他（一个字）" onChange={(e) => setOther(e.target.value)} />
              <button className="cr-btn" disabled={busy || !other}
                onClick={() => submit(cur, { verdict: 'other', other_char: other })}>其他 <kbd>o</kbd></button>
            </span>
          </div>

          <label className="cr-note">备注（可空，≤500 字）
            <textarea value={note} maxLength={500} rows={2} onChange={(e) => setNote(e.target.value)} />
          </label>

          <div className="cr-nav">
            <button className="cr-btn" disabled={idx === 0} onClick={() => go(-1)}>← 上一格</button>
            <button className="cr-btn" disabled={idx >= cells.length - 1} onClick={() => go(1)}>下一格 →</button>
          </div>
        </div>
      )}

      {view && (
        <div className="card cr-list">
          {cells.map((c, i) => {
            const dd = decOf(c)
            return (
              <button key={c.cell_id} className={`cr-row${i === idx ? ' cur' : ''}${dd ? ' done' : ''}`}
                onClick={() => setIdx(i)}>
                <code>{c.cell_id}</code> <span>{c.char}</span> <span className="muted">{dd ? V_LABEL[dd.verdict] : '未裁'}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
