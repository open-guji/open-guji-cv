import { useState } from 'react'
import { needsReading } from '../../domain'
import type { AroundContext, RareCandidate, ReviewCard } from '../../types/review'
import type { KeyItem } from './candidates'
import type { Verdict } from './ReviewPanel'

interface Props {
  idx: number
  c: ReviewCard
  book: string
  isCurrent: boolean
  verdict?: Verdict
  keys: KeyItem[]
  ctxImgOpen: boolean
  aroundCtx?: AroundContext
  rareOut?: RareCandidate[] | 'loading' | 'error'
  onFocus: () => void
  onSet: (shape: string, reading?: string, done?: string) => void
  onSetNoGlyphLib: (checked: boolean) => void
  onToggleCtxImg: () => void
  onFetchRare: (force?: boolean) => void
  contextImgSrc: string
}

export function ReviewCardView({
  idx, c, isCurrent, verdict, keys, ctxImgOpen, aroundCtx, rareOut,
  onFocus, onSet, onSetNoGlyphLib, onToggleCtxImg, onFetchRare, contextImgSrc,
}: Props) {
  const v = verdict || { shape: '', reading: '', done: '' }
  // shape/reading 的唯一改动入口都在本组件内（候选点击、输入框、标记按钮），
  // 所以本地 state 与 verdict 不会失步；不用受控于 prop。
  const [shapeInput, setShapeInput] = useState(v.shape || '')
  const [readingInput, setReadingInput] = useState(v.reading || '')

  const ocr = (c.ocr || []).slice(0, 2)
  const doubts = (c.doubts || []).map((d, i) => <div key={i} className="rvdoubt">⚠ {d}</div>)
  const fm = c.form && c.form.state === 'open' ? c.form : null
  const showReading = needsReading(v.shape) || (!!v.reading && v.reading !== v.shape)

  function pick(ch: string, reading?: string) {
    setShapeInput(ch)
    setReadingInput(reading ?? (needsReading(ch) ? '' : ch))
    onSet(ch, reading ?? (needsReading(ch) ? readingInput : ch))
  }

  function onShapeInput(val: string) {
    setShapeInput(val)
    onSet(val, readingInput, undefined)
  }
  function onReadingInput(val: string) {
    setReadingInput(val)
    onSet(shapeInput, val, undefined)
  }

  return (
    <div id={`rvc${idx}`} className={`rvcard${isCurrent ? ' cur' : ''}`} data-done={v.done || ''} data-nolib={v.noGlyphLib ? '1' : ''}
         onClick={onFocus}>
      <div className="rvhead">
        <b className="rvsel">{c.id}</b><span className="muted">{c.channel || '待审'}</span>
        <label className="rvnolib" title="字形有无法修复的噪声（污墨/裂纹等），这次选字正常裁决，但这张图不进字形库">
          <input type="checkbox" checked={!!v.noGlyphLib}
                 onChange={(e) => { e.stopPropagation(); onSetNoGlyphLib(e.target.checked) }} /> 字形不入库
        </label>
      </div>
      <div className="rvbody">
        <div className="rvimgcol">
          <img src={c.patch} alt={c.id} loading="lazy" />
          <button className="rvctxbtn" onClick={(e) => { e.stopPropagation(); onToggleCtxImg() }}
                  title="切分/缩框前的列图原样，上下各带 2 格">看原图</button>
        </div>
        <div className="rvev">
          <div><span className="k">整理本</span> {c.ref?.char
            ? <><b>{c.ref.char}</b><span className="rvp">{c.ref.op}{c.ref.form ? ` · 惯刻 ${c.ref.form}` : ''}</span></>
            : <span className="muted">—</span>}</div>
          <div><span className="k">库</span> {c.db ? `${c.db.verdict} ${c.db.cov}` : '—'}</div>
          <div><span className="k">上下文</span> {c.ctx?.char
            ? <><button className="rvtake" onClick={(e) => { e.stopPropagation(); onFocus(); pick(c.ctx!.char!) }}
                        title={`采信上下文定的字（margin ${c.ctx.margin}）`}>{c.ctx.char}</button>
                <span className="rvp">m={c.ctx.margin}</span></>
            : '—'}
            {c.ctx?.llm_suggestion && (
              <button className="rvtake" onClick={(e) => { e.stopPropagation(); onFocus(); pick(c.ctx!.llm_suggestion!) }}
                      title="Step6 上下文裁决 margin 不够时问了线上大模型，这是它的建议（只调过候选顺序，未自动放行，见 Step6 大模型调用记录页）">
                🤖{c.ctx.llm_suggestion}
              </button>
            )}</div>
          <div><span className="k" title="Paddle OCR，准确率一般，只作参考">OCR</span> {ocr.length
            ? ocr.map(([ch, p], i) => (
                <span key={i}>
                  <button className="rvtake" onClick={(e) => { e.stopPropagation(); onFocus(); pick(ch) }}
                          title={`采信这个字（OCR 概率 ${Number(p).toFixed(3)}）`}>{ch}</button>
                  <span className="rvp">{Number(p).toFixed(2)}</span>
                </span>
              ))
            : '—'}</div>
          {doubts}
        </div>
      </div>
      {ctxImgOpen && <div className="rvctximg"><img src={contextImgSrc} alt="上下文原图" /></div>}
      {fm && (
        <div className="rvform">
          <span className="k" title="整理本对这一组只用一种形，它定得了义定不了形">义定形未定 · 整理本「{fm.semantic}」</span>
          {fm.forms.map((f) => {
            const hn = (fm.human || {})[f] || 0
            const lib = (fm.lib || []).find((x) => x[0] === f)
            return (
              <button key={f} className={`rvformpick${v.shape === f ? ' pick' : ''}`}
                      onClick={(e) => { e.stopPropagation(); onFocus(); pick(f, fm.semantic) }}
                      title={`${hn ? `本书人裁确认过 ${hn} 次` : '本书还没人确认过这个形（首例）'}${lib ? ` · 库 cov ${lib[1]}` : ''}`}>
                {f}<sub>{hn ? `人${hn}` : '新'}</sub>
              </button>
            )
          })}
        </div>
      )}
      <div className="rvcand">
        <span className="rvbtns">
          {keys.map((e, i) => e.ch ? (
            <button key={i} className={`rvpick${v.shape === e.ch ? ' pick' : ''}${e.nokey ? ' nokey' : ''}`}
                    onClick={(ev) => { ev.stopPropagation(); onFocus(); pick(e.ch) }} title={e.note}>
              {e.keys.length ? `${e.keys.join('/')}·` : ''}{e.ch}<sub className="rvsrc">{e.srcs.join('·')}</sub>
            </button>
          ) : (
            <span key={i} className="rvwait" title={e.note}>{e.keys.join('/')}·…<sub className="rvsrc">形</sub></span>
          ))}
        </span>
        <input className="rvin" placeholder="字" value={shapeInput}
               onClick={(e) => e.stopPropagation()}
               onChange={(e) => onShapeInput(e.target.value)} />
        {showReading && (
          <span className="rvread">
            {' '}→ <input className="rvin" placeholder="文意" value={readingInput}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => onReadingInput(e.target.value)}
                          title="己/已/巳 才需要：图上刻的是左边那个，这里填文意该读的" />
          </span>
        )}
      </div>
      <div className="rvseg">
        <button className={`rvmark${v.done === 'truncated' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet('', '', v.done === 'truncated' ? '' : 'truncated') }}
                title="本字的笔画被切掉了一部分（T）">字形不完整</button>
        <button className={`rvmark${v.done === 'contaminated' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet('', '', v.done === 'contaminated' ? '' : 'contaminated') }}
                title="混进了邻字残墨 / 界行 / 版框（C）">有噪声</button>
        <button className={`rvmark${v.done === 'non' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet('', '', v.done === 'non' ? '' : 'non') }}
                title="这一格根本不是字（N）">非字</button>
        <button className={`rvmark${v.done === 'skip' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet('', '', v.done === 'skip' ? '' : 'skip') }}
                title="真拿不准，留给以后（S）">跳过</button>
      </div>
      {aroundCtx && (
        <div className="rvctx">
          {aroundCtx.slots.map((s, k) => {
            const ch = s.char || '□'
            if (k === aroundCtx.at) return <mark key={k}>{ch}</mark>
            const cls = s.review ? 'ctx-rev' : (s.source === 'db' || s.source === 'ocr' ? 'ctx-w' : '')
            return cls ? <span key={k} className={cls}>{ch}</span> : <span key={k}>{ch}</span>
          })}
        </div>
      )}
      <div className="rvrare">
        <button className="rvrarebtn" onClick={(e) => { e.stopPropagation(); onFetchRare(true) }}>查候选</button>
        <span className="muted">字体模板 + CNN 融合，10 个；带释义与整理本对应字</span>
      </div>
      <div className="rvrareout">
        {rareOut === 'loading' && '候选加载中…'}
        {rareOut === 'error' && '加载失败'}
        {Array.isArray(rareOut) && (rareOut.length ? rareOut.map((x, i) => (
          <div className="rvrrow" key={i}>
            <button className="rvpick rvrarepick" onClick={(ev) => { ev.stopPropagation(); onFocus(); pick(x.char) }}
                    title={`${x.py ? x.py + ' · ' : ''}相似度 ${x.score} · ${x.font} · ${x.ids || '—'} · ${x.cp}`}>{x.char}</button>
            {x.std
              ? <b className="rvstd" title={`整理本里用的是这个字（${x.std_freq} 次）`}>→ {x.std}</b>
              : (x.freq ? <span className="rvin" title={`整理本里用过 ${x.freq} 次`}>【整】</span> : null)}
            <span className="rvgloss" title={x.gloss || ''}>{x.gloss || ''}</span>
            <a className="rvzi" href={x.zi} target="_blank" rel="noopener noreferrer">字统网</a>
          </div>
        )) : '没有候选')}
      </div>
    </div>
  )
}
