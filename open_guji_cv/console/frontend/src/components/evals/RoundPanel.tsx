import { useState } from 'react'
import { fetchRound } from '../../api/evals'
import type { RoundResponse } from '../../types/evals'
import { RateHistory } from './RateHistory'

const RD_MARK: Record<string, string> = { green: '✓ 绿', yellow: '~ 黄', red: '✗ 红', none: '—' }
const RD_CLS: Record<string, string> = { green: 'qok', yellow: '', red: 'qbad', none: 'muted' }

// 迁移自 v1 health.js::loadRound。一轮体检：四个判据 + 下一批页码。
// 绿=继续跑，黄=记着别动算法（样本不够时改算法是在拟合噪声），红=停下修。
export function RoundPanel({ book, pages, onFillPages }: { book: string; pages: string; onFillPages: (p: string) => void }) {
  const [d, setD] = useState<RoundResponse | null>(null)
  const [msg, setMsg] = useState('')

  async function load() {
    setMsg('体检中…（要读产物与金标，十几秒）')
    try {
      const r = await fetchRound(book, pages || 'dev_set')
      setD(r)
      setMsg('')
    } catch (e) {
      setMsg('体检失败：' + (e as Error).message)
    }
  }

  const pct = (pair: [number, number]) => (pair[1] ? `${(pair[0] / pair[1] * 100).toFixed(2)}%` : '—')

  const rows: React.ReactNode[] = []
  if (d?.A) {
    const a = d.A
    rows.push(
      <tr key="A">
        <td className="mono">A</td>
        <td>自动放行错误率{a.light !== 'green' && <div className="qs">先看图：管线错？金标错？还是你被坏图块误导？</div>}</td>
        <td className={`mono ${RD_CLS[a.light]}`}>{RD_MARK[a.light]}</td>
        <td className="qs">
          整理本 {a.gold[0]}/{a.gold[1]} = {pct(a.gold)}{a.human[1] ? <> · 你的裁决 {a.human[0]}/{a.human[1]} = {pct(a.human)}</> : null}
          {a.errors?.length > 0 && (
            <div className="qerr">{a.errors.slice(0, 4).map((e, i) => <span key={i}>{i > 0 && ' · '}{e.id} 判「{e.pred}」金标「{e.gold}」</span>)}</div>
          )}
        </td>
      </tr>,
    )
  }
  if (d?.B) {
    const b = d.B
    rows.push(
      <tr key="B">
        <td className="mono">B</td>
        <td>人审率</td>
        <td className={`mono ${RD_CLS[b.light]}`}>{RD_MARK[b.light]}</td>
        <td className="qs">
          {b.review}/{b.total} = {(b.rate * 100).toFixed(2)}%
          {b.excluded ? <span className="qs">（另有 {b.excluded} 格在排除名单里，不进分母）</span> : null}
          <RateHistory book={book} />
          {b.by_page.length > 0 && <div className="qs">{b.by_page.map((r) => `p${r.page}:${r.n}`).join(' ')}</div>}
        </td>
      </tr>,
    )
  }
  if (d?.C) {
    const c = d.C
    rows.push(
      <tr key="C">
        <td className="mono">C</td>
        <td>缺陷聚集（累计 {c.total} 条）{c.worst ? <div className="qs"><b>停下修算法</b>：孤例是个案，扎堆才是系统性问题</div> : <div className="qs">孤例是个案，扎堆才是系统性问题；黄灯先记着别动算法</div>}</td>
        <td className={`mono ${RD_CLS[c.light]}`}>{RD_MARK[c.light]}</td>
        <td className="qs">{c.rows.slice(0, 5).map((r, i) => (
          <div key={i}>格位 {r.slot}: {r.n} 条/{r.pages} 页{c.worst && r.slot === c.worst.slot ? ' ← 扎堆' : ''}</div>
        ))}</td>
      </tr>,
    )
  }
  if (d?.C2) {
    const t = d.C2
    rows.push(
      <tr key="C2">
        <td className="mono">C2</td>
        <td>字距（挤排页）{t.rows.length > 0 && <div className="qs">这几页字<b>物理相连</b>，切分做不到完美；人审会偏多，标缺陷即可，<b>不算算法退步</b></div>}</td>
        <td className={`mono ${RD_CLS[t.light]}`}>{RD_MARK[t.light]}</td>
        <td className="qs">{t.rows.length
          ? t.rows.map((r, i) => <div key={i}>p{r.page} 间隙中位 {r.median_gap}px，{(r.near_ratio * 100).toFixed(0)}% 不足 5px</div>)
          : '字距正常'}</td>
      </tr>,
    )
  }
  if (d?.D && d.D.rate != null) {
    const x = d.D
    rows.push(
      <tr key="D">
        <td className="mono">D</td>
        <td>生僻字 top-10（字体模板+CNN 融合）{!x.cnn && <div className="qs">没有 CNN checkpoint，退回纯 HOG——数字会明显低</div>}</td>
        <td className={`mono ${RD_CLS[x.light]}`}>{RD_MARK[x.light]}</td>
        <td className="qs">{x.hit}/{x.n} = {(x.rate * 100).toFixed(1)}%{x.note ? ` · ${x.note}` : ''}</td>
      </tr>,
    )
  }
  if (d?.E) {
    const e = d.E
    const fa = e.form_auto || [0, 0]
    rows.push(
      <tr key="E">
        <td className="mono">E</td>
        <td>字形保真率（自动放行的异体位，字形须与人裁完全一致）{e.light === 'none' && <div className="qs">去「异体 → 组视图」照准一批，攒够 50 条才亮灯</div>}</td>
        <td className={`mono ${RD_CLS[e.light]}`}>{RD_MARK[e.light]}</td>
        <td className="qs">
          {e.audited ? <>人裁核过 {e.hit}/{e.audited} = {(e.rate * 100).toFixed(1)}%（Wilson 下界 {e.wilson_low}；variant_form 定形 {fa[0]}/{fa[1]}）</> : '还没有人裁核过的异体位'}
          <div className="qs">异体位自动放行 {e.variant_admits} 条 · 义定形未定待审 {e.form_open} 条{e.note ? ` · ${e.note}` : ''}</div>
          {e.errors?.length > 0 && <div className="qerr">{e.errors.slice(0, 4).map((x, i) => <span key={i}>{i > 0 && ' · '}{x.id} 存「{x.pred}」人裁「{x.human}」</span>)}</div>}
        </td>
      </tr>,
    )
  }
  if (d?.F && d.F.n_cells) {
    const f = d.F
    const bt = f.by_type || {}
    const tstr = (['T1', 'T2'] as const).filter((k) => bt[k]).map((k) =>
      `${k}${k === 'T1' ? '版本注' : '案語'} ${bt[k].n_review}/${bt[k].n_cells} = ${(bt[k].rate * 100).toFixed(2)}%`,
    ).join(' · ')
    rows.push(
      <tr key="F">
        <td className="mono">F</td>
        <td>夹注（雙行小注）人审率与丢字率{f.n_lost > 0 && <div className="qs">段格数与 a/b 不匹配 = 丢数据，比认错字严重，先修切分</div>}</td>
        <td className={`mono ${RD_CLS[f.light]}`}>{RD_MARK[f.light]}</td>
        <td className="qs">
          人审 {f.n_review}/{f.n_cells} = {(f.rate * 100).toFixed(2)}% · 段 {f.n_segments}（有整理本参照 {f.n_segments_with_ref}）
          {tstr && <div className="qs">{tstr}</div>}
          <div className="qs">丢字 {f.n_lost} 段{f.lost_rate != null ? `（${(f.lost_rate * 100).toFixed(1)}%）` : ''}{f.n_no_ref ? ` · 锚不上整理本 ${f.n_no_ref} 段（多为 T2 案語）` : ''}</div>
          {f.lost?.length > 0 && <div className="qerr">{f.lost.slice(0, 4).map((x, i) => <span key={i}>{i > 0 && ' · '}p{x.page} c{x.col} a{x.a}/b{x.b}</span>)}</div>}
        </td>
      </tr>,
    )
  }

  const nx = d?.next
  return (
    <div className="card">
      <h2>本轮体检 <span className="muted">四个判据决定：继续跑，还是停下修算法</span>
        <button onClick={load} style={{ float: 'right' }}>体检</button></h2>
      {!d && <div className="muted">{msg || '点「体检」——用「定字裁决」里那个页框的页码'}</div>}
      {d && (
        <>
          {rows.length > 0 ? (
            <table className="jobs"><thead><tr><th>#</th><th>判据</th><th>灯</th><th>数</th></tr></thead><tbody>{rows}</tbody></table>
          ) : <div className="qs">没填页码，只给下一批建议。</div>}
          {nx && nx.batch.length > 0 ? (
            <div className="qs round-next">
              下一批（正文页，已跳过职名/目录页）：<span className="mono">{nx.batch.join(',')}</span>{' '}
              <button onClick={() => onFillPages(nx.batch.join(','))}>填入页框</button>
              <div className="qs">正文页 {nx.body_total}，已处理 {nx.done}，剩 {nx.todo}</div>
            </div>
          ) : <div className="qs round-next">正文页跑完了。</div>}
        </>
      )}
    </div>
  )
}
