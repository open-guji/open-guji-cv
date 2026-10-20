import { useEffect, useState } from 'react'
import { fetchRareAlt } from '../../api/review'
import { libFontUrl } from '../../api/glyphlib'
import type { AltCand, ReviewCard } from '../../types/review'
import { ALT_SHOW, cardPivots } from './altPivots'

type Out = { pivots: string[]; candidates: AltCand[] } | 'loading' | 'error'
const memo = new Map<string, Out>()          // 翻回来不重查；键＝字位＋近似字＋人键入的字

/** 字形图：先 I.Ming（明体，近刻本），没有就 Jigmo（到扩展 G），都没有只显示字。 */
function Glyph({ ch }: { ch: string }) {
  const [font, setFont] = useState<'iming' | 'jigmo' | ''>('iming')
  if (!font) return <span className="rvaltch">{ch}</span>
  return <img className="rvaltimg" src={libFontUrl(ch, font)} alt={ch} loading="lazy"
              onError={() => setFont(font === 'iming' ? 'jigmo' : '')} />
}

/**
 * 相似字（以字找字）：近似字的异体族（本仓异体表＋部件檢索＋字统网）按这格字块图排序（/api/rare/alt）。
 * 卡成为当前卡时才查；缺省展开 ALT_SHOW 个，其余点「再看」。另有一个框：键入你认出的近似字，按它重查。
 * 点一个＝选这个字（同候选按钮）。只出候选，不进放行。
 */
export function AltPanel({ book, c, active, onPick }: {
  book: string; c: ReviewCard; active: boolean; onPick: (ch: string) => void
}) {
  const pivots = cardPivots(c)
  const [q, setQ] = useState('')
  const [asked, setAsked] = useState('')
  const [all, setAll] = useState(false)
  const [forced, setForced] = useState(false)
  const [, bump] = useState(0)
  const key = `${c.id}|${pivots.join('')}|${asked}`
  const ask = () => { setAsked([...q.trim()][0] || ''); setAll(false); setForced(true) }
  const want = active || forced
  const out: Out | undefined = memo.get(key) ?? (want ? 'loading' : undefined)

  useEffect(() => {
    if (!want || memo.has(key)) return
    memo.set(key, 'loading')
    fetchRareAlt(book, c.page, c.col, c.slot, { sub: c.sub, pivots, q: asked })
      .then(d => memo.set(key, d), () => memo.set(key, 'error'))
      .finally(() => bump(n => n + 1))
  }, [want, key])                            // eslint-disable-line react-hooks/exhaustive-deps

  const list = out && typeof out === 'object' ? out.candidates : []
  const shown = all ? list : list.slice(0, ALT_SHOW)
  return (
    <div className="rvalt" onClick={(e) => e.stopPropagation()}>
      <div className="rvalthead">
        相似字
        <span className="muted">（{out && typeof out === 'object' && out.pivots.length
          ? `从 ${out.pivots.join('、')} 的异体字里，按和这格字图的相像程度排`
          : '近似字的异体字按字图相像程度排'}）</span>
        <span className="rvaltq">
          <input value={q} maxLength={2} placeholder="近似字" title="键入你认出的近似字，查它的异体字（字统网没缓存的会联网取一次）"
                 onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); ask() } }} />
          <button onClick={ask}>以字找字</button>
        </span>
      </div>
      {!active && !forced && !out && <button className="rvaltmore" onClick={() => setForced(true)}>查相似字</button>}
      {out === 'loading' && <span className="muted">查找中…</span>}
      {out === 'error' && <span className="muted">查找失败</span>}
      {out && typeof out === 'object' && !list.length && <span className="muted">没有找到</span>}
      <div className="rvaltgrid">
        {shown.map(a => (
          <button key={a.c} className="rvaltbtn" onClick={() => onPick(a.c)}
                  title={`${a.p && a.p !== a.c ? `从「${a.p}」查到 · ` : ''}像 ${Math.floor(a.s * 100)}% · ${a.src}`}>
            <Glyph ch={a.c} />
            <span>{a.c}</span>
          </button>
        ))}
        {list.length > ALT_SHOW && (
          <button className="rvaltmore" onClick={() => setAll(v => !v)}>
            {all ? '收起' : `再看 ${list.length - ALT_SHOW} 个`}
          </button>
        )}
      </div>
    </div>
  )
}
