import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchStep9Progress } from '../../api/step9'
import type { Step9ProgressResponse, Step9ProgressRow } from '../../api/step9'

// Step9 · 9.0 待办看板（用户 2026-09-20：「单独的卡片，打开这一页时直接读取，再给一个刷新按钮」）。
// 看板不是闸：有待办也照样能跑 9.1/9.2。口径见 report/progress.py。
//
// 设计（dataviz skill「Figures - when the form is a number」）：
// - 六个 stat tile 在上：label + 值（proportional figures、semibold），零用 faint；
// - 表只列有待办的页，数字列 tabular-nums 右对齐，零画成「·」不占视线；
// - 「过期的步」不再逐个列 13 个名字：压成「从 border_detect 起 13 步」一枚 chip——
//   这一列想说的是"从哪一步开始要重跑"，不是名单。
// - 状态色只给「过期」这一档（ochre），且必带文字，不靠颜色单独传达。

const STEP_ORDER = ['border_detect', 'border_detect_gate', 'column_warp', 'column_gate', 'row_segment',
  'row_segment_gate', 'cell_shrink', 'glyph_match', 'ocr_candidates', 'rare_candidates',
  'align_ref', 'context_decide', 'seed_admit']

function staleChip(steps: string[]): { text: string; from: string } | null {
  if (!steps.length) return null
  const names = steps.map((s) => s.split(':')[0])
  const first = [...names].sort((a, b) => STEP_ORDER.indexOf(a) - STEP_ORDER.indexOf(b))[0]
  const missing = steps.some((s) => s.endsWith(':missing'))
  const n = steps.length
  return { from: first, text: n === 1 ? `${first}${missing ? ' 缺失' : ' 过期'}` : `从 ${first} 起 ${n} 步${missing ? '（含缺失）' : ''}` }
}

function Num({ v }: { v: number }) {
  return v ? <span className="pb-n">{v}</span> : <span className="pb-zero">·</span>
}

function hasTodo(r: Step9ProgressRow) {
  return !!(r.stale || r.review || r.cut || r.defect || r.cols_bad)
}

export function ProgressBoard({ book, pages }: { book: string; pages: string }) {
  const [data, setData] = useState<Step9ProgressResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [at, setAt] = useState('')
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    if (!book) return
    setBusy(true); setErr('')
    try {
      setData(await fetchStep9Progress(book, pages.trim() || 'all'))
      setAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [book, pages])

  // 打开即读；页范围改了缓 500ms 再读（人还在打字时别每敲一个字就查一遍）
  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { void load() }, data ? 500 : 0)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load])

  const t = data?.totals
  const rows = data ? data.pages.filter(hasTodo) : []
  const stalePages = data ? data.pages.filter((r) => r.stale > 0).length : 0
  // 全书共同的"从哪一步起过期"：取各页最靠上那一步里最常见的
  let staleFrom: string | null = null
  let commonStale = 0
  if (data && stalePages) {
    const cnt = new Map<string, number>()
    const cntN = new Map<number, number>()
    for (const r of data.pages) {
      const c = staleChip(r.stale_steps)
      if (c) { cnt.set(c.from, (cnt.get(c.from) || 0) + 1); cntN.set(r.stale, (cntN.get(r.stale) || 0) + 1) }
    }
    staleFrom = [...cnt.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
    commonStale = [...cntN.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 0
  }

  return (
    <div className="card pb">
      <div className="pb-head">
        <h2>待办看板</h2>
        {data && <span className="muted">{data.n_pages} 页 · {data.n_clean} 页无待办</span>}
        <span className="pb-spacer" />
        {at && <span className="muted pb-at">更新于 {at}</span>}
        <button className="ghost" onClick={() => void load()} disabled={busy}>{busy ? '读取中…' : '刷新'}</button>
      </div>

      {err && <p className="pb-err">读取失败：{err}</p>}

      {t && (
        <div className="pb-tiles">
          <Tile label="过期页" value={stalePages} tone={stalePages ? 'ochre' : undefined} />
          <Tile label="待审字位" value={t.review} />
          <Tile label="切线待裁" value={t.cut} />
          <Tile label="阙文占位" value={t.defect} />
          <Tile label="坏列" value={t.cols_bad} />
          <Tile label="非字（已了结）" value={t.excluded} dim />
        </div>
      )}

      {t && stalePages > 0 && (
        <p className="pb-note pb-note-ochre">
          {stalePages} 页从 <code>{staleFrom}</code> 起过期——后面几列是旧产物算的，先重跑再信数。
        </p>
      )}
      {data && !rows.length && <p className="pb-note pb-note-ok">这一段没有待办。</p>}

      {rows.length > 0 && (
        <div className="pb-scroll">
          <table className="pb-table">
            <thead>
              <tr><th>页</th><th>过期</th><th>待审</th><th>切线</th><th>阙文</th><th>坏列</th><th className="pb-dim">非字</th><th className="pb-left">从哪一步起</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                // 与全书共同情形相同的行不再重复那枚 chip（上面的提示行已经说了），
                // 只有"这一页跟别的页不一样"才值得占一格视线。
                let chip = staleChip(r.stale_steps)
                if (chip && chip.from === staleFrom && r.stale === commonStale) chip = null
                return (
                  <tr key={r.page}>
                    <td className="pb-page">{r.page}</td>
                    <td><Num v={r.stale} /></td><td><Num v={r.review} /></td><td><Num v={r.cut} /></td>
                    <td><Num v={r.defect} /></td><td><Num v={r.cols_bad} /></td>
                    <td className="pb-dim"><Num v={r.excluded} /></td>
                    <td className="pb-left">{chip ? <span className="pb-chip">{chip.text}</span> : ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted pb-foot">看板不是闸：有待办也照样能跑 9.1 / 9.2。</p>
    </div>
  )
}

function Tile({ label, value, tone, dim }: { label: string; value: number; tone?: 'ochre'; dim?: boolean }) {
  return (
    <div className={'pb-tile' + (dim ? ' pb-tile-dim' : '')}>
      <div className="pb-tile-label">{label}</div>
      <div className={'pb-tile-value' + (value ? (tone ? ` pb-${tone}` : '') : ' pb-zero')}>{value}</div>
    </div>
  )
}
