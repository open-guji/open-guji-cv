import { useState } from 'react'
import { BinaryToggleImage } from '../common/BinaryToggleImage'
import type { AroundContext, RareCandidate, ReviewCard } from '../../types/review'
import { disagreeingRuns, dropReason, groupById } from './ai'
import type { KeyItem } from './candidates'
import type { Verdict } from './ReviewPanel'
import { ctxChar, isJysCard, JYS_OPTIONS } from './reviewClass'

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
  onSet: (shape: string, done?: string) => void
  onSetNoGlyphLib: (checked: boolean) => void
  onSetGuess: (guess: string) => void
  /** 无匹配（近似字）勾选与 IDS／备注（overview#276）。老调用方不传就不显示这一栏。 */
  onSetApprox?: (patch: Pick<Verdict, 'approx' | 'approxIds' | 'approxNote'>) => void
  onToggleCtxImg: () => void
  onFetchRare: (force?: boolean) => void
  contextImgSrc: string
  /** 这张卡的类别（overview#247，按类别审时才有）；决定卡片样式。 */
  cls?: string
  /** 己已巳卡：人点了「都不是」→ 展开成普通卡。 */
  jysOpen?: boolean
  onJysNone?: () => void
  /** 上下文显示刻本读法（缺省显示整理本对位原文）。 */
  ctxKeben?: boolean
}

export function ReviewCardView({
  idx, c, isCurrent, verdict, keys, ctxImgOpen, aroundCtx, rareOut,
  onFocus, onSet, onSetNoGlyphLib, onSetGuess, onSetApprox, onToggleCtxImg, onFetchRare, contextImgSrc,
  cls, jysOpen = false, onJysNone, ctxKeben = false,
}: Props) {
  const v = verdict || { shape: '', done: '' }
  // 字的唯一改动入口都在本组件内（候选点击、输入框、标记按钮），
  // 所以本地 state 与 verdict 不会失步；不用受控于 prop。
  const [shapeInput, setShapeInput] = useState(v.shape || '')
  const [guessInput, setGuessInput] = useState(v.guess || '')
  const [idsInput, setIdsInput] = useState(v.approxIds || '')
  const [noteInput, setNoteInput] = useState(v.approxNote || '')

  const ocr = (c.ocr || []).slice(0, 2)
  const doubts = (c.doubts || []).map((d, i) => <div key={i} className="rvdoubt">⚠ {d}</div>)
  const fm = c.form && c.form.state === 'open' ? c.form : null

  function pick(ch: string) {
    setShapeInput(ch)
    onSet(ch)
  }

  function onShapeInput(val: string) {
    setShapeInput(val)
    onSet(val, undefined)
  }

  // 上下文：整理本对位原文优先，刻本读法在开关后面（#247）。己已巳卡把本位遮成「？」——
  // 三选一要人读文意，别让整理本在这一格印的字替人答了（整理本自己也把「而已」印成「而巳」）。
  function ctxLine(hideAt: boolean) {
    if (!aroundCtx) return null
    return (
      <div className="rvctx" title={ctxKeben ? '刻本读法（定字 → 库 → OCR）' : '整理本对位原文；灰字 = 这一格对不上整理本，退回刻本定字'}>
        {aroundCtx.slots.map((s, k) => {
          if (k === aroundCtx.at) return <mark key={k}>{hideAt ? '？' : ctxChar(s, ctxKeben)}</mark>
          const ch = ctxChar(s, ctxKeben)
          // 浅一档：整理本口径下 = 这一格对不上整理本、退回了定字；刻本口径下 = 库/OCR 兜底字（改前的规则）
          const useKeben = ctxKeben || s.text_src === undefined      // 老后端没给整理本字段
          const weak = useKeben ? (s.source === 'db' || s.source === 'ocr')
                                : !(s.text_src === 'ref' || s.text_src === 'coord')
          const cls2 = s.review ? 'ctx-rev' : (weak ? 'ctx-w' : '')
          return cls2 ? <span key={k} className={cls2}>{ch}</span> : <span key={k}>{ch}</span>
        })}
      </div>
    )
  }

  // ── 己已巳专用卡（#247）：只给三个选项 + 「都不是」；不显示整理本、库分、次选、OCR ──
  if (isJysCard(cls, jysOpen)) {
    return (
      <div id={`rvc${idx}`} className={`rvcard rvjys${isCurrent ? ' cur' : ''}`} data-done={v.done || ''} data-cls={cls}
           onClick={onFocus}>
        <div className="rvhead">
          <b className="rvsel">{c.id}</b><span className="muted">己已巳 · 按文意三选一</span>
        </div>
        <div className="rvbody">
          <BinaryToggleImage
            src={c.patch} alt={c.id}
            extra={
              <button className="bti-btn" onClick={(e) => { e.stopPropagation(); onToggleCtxImg() }}
                      title="切分/缩框前的列图原样，上下各带 2 格">看原图</button>
            } />
          <div className="rvjys-ctx">{ctxLine(true) ?? <span className="muted">上下文加载中…</span>}</div>
        </div>
        {ctxImgOpen && <div className="rvctximg"><img src={contextImgSrc} alt="上下文原图" /></div>}
        <div className="rvjys-opts">
          {JYS_OPTIONS.map((o) => (
            <button key={o.ch} className={`rvjys-pick${v.shape === o.ch && v.done ? ' pick' : ''}`}
                    onClick={(e) => { e.stopPropagation(); onFocus(); pick(o.ch) }} title={`${o.ch}：${o.hint}（${o.key}）`}>
              <kbd>{o.key}</kbd>{o.ch}
            </button>
          ))}
          <button className="rvjys-none" onClick={(e) => { e.stopPropagation(); onFocus(); onJysNone?.() }}
                  title="图上刻的不是这一族的字（切错了、或是别的字）：展开成普通卡自己挑（4）">
            <kbd>4</kbd>都不是
          </button>
        </div>
      </div>
    )
  }

  return (
    <div id={`rvc${idx}`} className={`rvcard${isCurrent ? ' cur' : ''}`} data-done={v.done || ''} data-nolib={v.noGlyphLib ? '1' : ''} data-approx={v.approx ? '1' : ''}
         data-cls={cls || undefined} onClick={onFocus}>
      <div className="rvhead">
        <b className="rvsel">{c.id}</b><span className="muted">{c.channel || '待审'}</span>
        {c.occluded && (
          <span className="rvoccl" title="印章／大片污损遮挡：默认用整理本的字，字形不进字形库（overview#195）。确认一下即可，也可在上方「按原因」里整组一键确认">
            印章遮挡 · {c.occluded.ref_blank ? '默认非字（整理本此位空）' : c.occluded.char ? `默认整理本字「${c.occluded.char}」` : '无默认字，请填'}
          </span>
        )}
        {c.stale_verdict && (
          <span className="rvstale"
                title={c.stale_verdict.withdrawn
                  ? `这一格 ${c.stale_verdict.ts.slice(0, 10)}（批次 ${c.stale_verdict.batch}）裁过，后来确认钉错了格、已从字形库撤下。没有预勾，请按图重新定字（overview#403）`
                  : `这一格 ${c.stale_verdict.ts.slice(0, 10)}（批次 ${c.stale_verdict.batch}）裁过，但切分改了或老裁决补不出锚，`
                    + `现在不作数（绑定 ${c.stale_verdict.status ?? '?'}）。已按当时的裁决预勾，看一眼图确认即可，会写出带现行锚点的新裁决（overview#403）`}>
            旧裁{c.stale_verdict.verdict.shape ? `「${c.stale_verdict.verdict.shape}」` : ''}{c.stale_verdict.withdrawn ? '已撤 · 请重新看' : '已失效 · 已预勾'}
          </span>
        )}
        {c.approx && (
          <span className="rvapproxhit"
                title={`库给的字靠的是近似例（无匹配·近似字）${c.approx.exemplar ? '：' + c.approx.exemplar : '：这个字在库里只有近似例'}`
                  + `${c.approx.ids ? '\nIDS ' + c.approx.ids : ''}${c.approx.note ? '\n' + c.approx.note : ''}`}>近似</span>
        )}
        <label className="rvnolib" title="字形有无法修复的噪声（污墨/裂纹等），这次选字正常裁决，但这张图不进字形库">
          <input type="checkbox" checked={!!v.noGlyphLib || !!c.occluded}
                 onChange={(e) => { e.stopPropagation(); onSetNoGlyphLib(e.target.checked) }} /> 字形不入库
        </label>
        {onSetApprox && (
          <label className="rvapprox" title="Unicode 里没有真正对应的字：所填的只是字形最像、意思最近的那个字。可展开填 IDS（实际结构）与备注">
            <input type="checkbox" checked={!!v.approx}
                   onChange={(e) => { e.stopPropagation(); onSetApprox({ approx: e.target.checked }) }} /> 无匹配（近似字）
          </label>
        )}
      </div>
      {onSetApprox && v.approx && (
        <div className="rvapproxin" onClick={(e) => e.stopPropagation()}>
          <input className="rvapproxids" placeholder="IDS（可空），如 ⿰氵⿱艹日" value={idsInput}
                 onChange={(e) => { setIdsInput(e.target.value); onSetApprox({ approxIds: e.target.value }) }}
                 title="这一格实际刻的结构（表意文字描述序列），可空" />
          <input className="rvapproxnote" placeholder="备注（可空）" value={noteInput}
                 onChange={(e) => { setNoteInput(e.target.value); onSetApprox({ approxNote: e.target.value }) }} />
        </div>
      )}
      <div className="rvbody">
        <BinaryToggleImage
          src={c.patch} alt={c.id}
          extra={
            <button className="bti-btn" onClick={(e) => { e.stopPropagation(); onToggleCtxImg() }}
                    title="切分/缩框前的列图原样，上下各带 2 格">看原图</button>
          } />
        <div className="rvev">
          <div><span className="k">整理本</span> {c.ref?.char
            ? <><b>{c.ref.char}</b><span className="rvp">{c.ref.op}{c.ref.form ? ` · 惯刻 ${c.ref.form}` : ''}</span></>
            : <span className="muted">—</span>}</div>
          <div><span className="k">库</span> {c.db ? `${c.db.verdict} ${c.db.cov}` : '—'}</div>
          {c.first && (
            <div className="rvfirst">
              <span className="k" title="借来的字形库上按字取 r5 embedding 均值原型检索（书 yaml params.review.first_pick）">CNN</span>{' '}
              {c.first.cnn_candidates.slice(0, 3).map(([ch, s], i) => (
                <span key={i}>
                  <button className="rvtake" onClick={(e) => { e.stopPropagation(); onFocus(); pick(ch) }}
                          title={`采信这个字（CNN 原型余弦 ${s}）`}>{ch}</button>
                  <span className="rvp">{Number(s).toFixed(2)}</span>
                </span>
              ))}
              {c.first.proto_src && (
                <span className="muted" title="CNN 首位的原型来源：本书自有库（own）优先，缺字才回退借来的库（borrow，冷启动）">
                  {c.first.proto_src === 'own' ? '本书库' : '借库'}
                </span>
              )}
              {c.first.agree === true && <span className="rvbadge rvbadge-ok" title="像素比对首位与 CNN 原型首位是同一个字">像素与CNN一致</span>}
              {c.first.agree === false && (
                <span className="rvbadge rvbadge-warn" title="像素比对首位与 CNN 原型首位不同——这类卡排在前面">
                  ⚠ 像素与CNN不一致：{c.first.pixel} / {c.first.cnn}
                </span>
              )}
              {c.first.agree === null && <span className="muted" title="有一路没给出候选">单路</span>}
            </div>
          )}
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
          {c.jys?.char && (
            <div><span className="k" title="己/已/巳 三字刻法不分，按上下文定：干支、时辰、「自己」一类搭配，其余为「已」">上下文定字</span>{' '}
              <button className="rvtake" onClick={(e) => { e.stopPropagation(); onFocus(); pick(c.jys!.char!) }}
                      title={`依据：${c.jys.why}`}>{c.jys.char}</button>
              <span className="rvp">{c.jys.why}</span></div>
          )}
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
      {c.ai && (() => {
        const disagree = disagreeingRuns(c.ai)
        const drop = c.ai.drop || []
        return (
          <div className="rvai" onClick={(e) => e.stopPropagation()}>
            <div className="rvai-badges">
              {c.ai.conflict_with_img && (
                <span className="rvbadge rvbadge-warn"
                      title="AI 首组不包含图像共识（库首选=OCR首选的那个字）">
                  ⚠ 疑似刻本讹字／整理本改字
                </span>
              )}
              {disagree && (
                <span className="rvbadge rvbadge-warn" title="两次运行给出的首组不一致">
                  ⚠ AI 拿不准：{disagree.join(' / ')}
                </span>
              )}
              {c.ai.confidence && <span className="rvp">AI 把握 {c.ai.confidence}</span>}
              {c.ai.need_human && <span className="muted">{c.ai.need_human}</span>}
            </div>
            <div className="rvai-groups">
              {(c.ai.rank || []).map((r, i) => {
                const g = groupById(c.groups, r.group)
                if (!g) return null
                return (
                  <div key={r.group} className={`rvai-group${i === 0 ? ' rvai-top' : ''}`}>
                    <span className="rvp">p={r.p.toFixed(2)}</span>
                    {g.members.map((m) => (
                      <button key={m} className={`rvpick${v.shape === m ? ' pick' : ''}`}
                              onClick={(e) => { e.stopPropagation(); onFocus(); pick(m) }}
                              title={g.why || undefined}>{m}</button>
                    ))}
                    {g.members.length > 1 && <span className="muted">同字异形</span>}
                    {(g.why || r.why) && (
                      <details className="rvai-why">
                        <summary>理由</summary>
                        {g.why && <div><span className="k">词典</span> {g.why}</div>}
                        {r.why && <div><span className="k">AI</span> {r.why}</div>}
                      </details>
                    )}
                  </div>
                )
              })}
            </div>
            {drop.length > 0 && (
              <details className="rvai-drop">
                <summary>排除 {drop.length} 项</summary>
                {drop.map((ch) => (
                  <div key={ch} className="rvai-dropitem">
                    <b>{ch}</b> <span className="muted">{dropReason(c.ai, ch)}</span>
                  </div>
                ))}
              </details>
            )}
          </div>
        )
      })()}
      {ctxImgOpen && <div className="rvctximg"><img src={contextImgSrc} alt="上下文原图" /></div>}
      {fm && (
        <div className="rvform">
          <span className="k" title="整理本对这一组只用一种形，它定得了义定不了形">义定形未定 · 整理本「{fm.semantic}」</span>
          {fm.forms.map((f) => {
            const hn = (fm.human || {})[f] || 0
            const lib = (fm.lib || []).find((x) => x[0] === f)
            return (
              <button key={f} className={`rvformpick${v.shape === f ? ' pick' : ''}`}
                      onClick={(e) => { e.stopPropagation(); onFocus(); pick(f) }}
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
      </div>
      <div className="rvseg">
        {/* 切分缺陷两档**保留已填的字**（用户 2026-09-20：「有噪声和字形不完整的，应该
            同时允许我选到底是哪个字——既不影响下一步整理，也反馈给了上游」）。
            别的档（非字/跳过/破损）本来就没有字可留，照旧清空。 */}
        <button className={`rvmark${v.done === 'truncated' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet(v.shape, v.done === 'truncated' ? (v.shape ? '1' : '') : 'truncated') }}
                title="本字的笔画被切掉了一部分（T）。可同时在上面选/填这是哪个字——字照样进文本，缺陷照样反馈给 Step3">字形不完整</button>
        {/* 「小注当正文」（overview#265）：字形不完整的一种——列尾双行小注被当成正文切成一格。
            事件照旧 seg_defect（quality=truncated），多带 reason=jiazhu_as_main。 */}
        <button className={`rvmark${v.done === 'jiazhu' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet(v.shape, v.done === 'jiazhu' ? (v.shape ? '1' : '') : 'jiazhu') }}
                title="双行小注被当成正文切成了一格（Z）。属字形不完整：不入库、退回切分">小注当正文</button>
        <button className={`rvmark${v.done === 'contaminated' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet(v.shape, v.done === 'contaminated' ? (v.shape ? '1' : '') : 'contaminated') }}
                title="混进了邻字残墨 / 界行 / 版框（C）。可同时选/填这是哪个字">有噪声</button>
        <button className={`rvmark${v.done === 'non' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet('', v.done === 'non' ? '' : 'non') }}
                title="这一格根本不是字（N）">非字</button>
        <button className={`rvmark${v.done === 'skip' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet('', v.done === 'skip' ? '' : 'skip') }}
                title="真拿不准，留给以后（S）">跳过</button>
        <button className={`rvmark${v.done === 'damaged' ? ' on' : ''}`}
                onClick={(e) => { e.stopPropagation(); onFocus(); onSet('', v.done === 'damaged' ? '' : 'damaged') }}
                title="原图就破损，字形认不出（D）。文本出 □，可在右边填最像的那个字">原图破损</button>
        {v.done === 'damaged' && (
          <span className="rvguess">
            {' '}□（？<input className="rvguessin" placeholder="最像" value={guessInput}
                           maxLength={4}
                           onClick={(e) => e.stopPropagation()}
                           onChange={(e) => { setGuessInput(e.target.value); onSetGuess(e.target.value) }}
                           title="最像的那个字，可空。只作文本括注，不进字形库" />）
          </span>
        )}
      </div>
      {ctxLine(false)}
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
