import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchStep9Progress } from '../../api/step9'
import type { Step9ProgressResponse, Step9ProgressRow } from '../../api/step9'

// Step9 · 9.0 待办看板（用户 2026-09-20：「单独的卡片，打开这一页时直接读取，再给一个刷新按钮」）。
// 看板不是闸：有待办也照样能跑 9.1/9.2。口径见 report/progress.py。
//
// 设计（dataviz skill「Figures - when the form is a number」）：
// - stat tile 在上：label + 值（proportional figures、semibold），零用 faint；
// - 表只列有待办的页，数字列 tabular-nums 右对齐，零画成「·」不占视线；
// - 「过期的步」不逐个列名字：压成「从 border_detect 起 13 步」一枚 chip，且与全书共同情形
//   相同的行不再重复（上面的提示行已经说了）。
// - 状态色只给「过期」这一档（ochre），且必带文字，不靠颜色单独传达。
//
// 「待审」拆成两列（用户 2026-09-20 同意，总览/13 §一·3）：**Step7 待人裁**（未放行 ∧ 未裁过，
// 与裁决台出卡数逐 id 相等）与 **已裁未放行**（人裁过、机器没采信）。合成一个数报给人，
// 裁决台只给前者的卡，人以为剩下的无处可做。

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

// 「有待办」不看非字与已裁未放行：前者是已了结的账，后者是人做完了等机器的账。
function hasTodo(r: Step9ProgressRow) {
  return !!(r.stale || r.review_new || r.cut || r.defect || r.cols_bad)
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
  // 全书共同的"从哪一步起过期"与共同的过期步数：取各页里最常见的
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
          <Tile label="Step7 待人裁" value={t.review_new} hint="= 定字裁决台出卡数" />
          <Tile label="切线待裁" value={t.cut} />
          <Tile label="阙文占位" value={t.defect} />
          <Tile label="坏列" value={t.cols_bad} />
          <Tile label="已裁未放行" value={t.review_decided} dim hint="人裁过、机器没采信" />
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
              <tr><th>页</th><th>过期</th><th>待人裁</th><th>切线</th><th>阙文</th><th>坏列</th><th className="pb-dim">已裁未放行</th><th className="pb-dim">非字</th><th className="pb-left">从哪一步起</th></tr>
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
                    <td><Num v={r.stale} /></td><td><Num v={r.review_new} /></td><td><Num v={r.cut} /></td>
                    <td><Num v={r.defect} /></td><td><Num v={r.cols_bad} /></td>
                    <td className="pb-dim"><Num v={r.review_decided} /></td>
                    <td className="pb-dim"><Num v={r.excluded} /></td>
                    <td className="pb-left">{chip ? <span className="pb-chip">{chip.text}</span> : ''}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted pb-foot">看板不是闸：有待办也照样能跑 9.1 / 9.2。「待人裁」与定字裁决台的卡逐 id 相等。</p>
    </div>
  )
}

function Tile({ label, value, tone, dim, hint }: { label: string; value: number; tone?: 'ochre'; dim?: boolean; hint?: string }) {
  return (
    <div className={'pb-tile' + (dim ? ' pb-tile-dim' : '')} title={hint}>
      <div className="pb-tile-label">{label}</div>
      <div className={'pb-tile-value' + (value ? (tone ? ` pb-${tone}` : '') : ' pb-zero')}>{value}</div>
    </div>
  )
}
