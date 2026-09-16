import { useState } from 'react'
import { fetchRareOne } from '../../api/review'
import type { RareCandidate } from '../../types/review'
import '../review/review.css' // 复用候选行样式 .rvrareout/.rvrrow/.rvstd/.rvgloss/.rvzi/.rvpick
import './rare.css'

// D7：Step5-b 生僻字候选独立视图。原来这一路候选只嵌在 Step7 定字卡片的
// "查候选"按钮里（见 review.js::rvFetchRare），本身从未有过独立页面——
// 方案 §三 指出这是需要单独露出来的一块（用户"今日想法"说的"Step5b"实际
// 对应这条代码，不是 variants 那块）。
// 后端只有单点查询接口（/api/rare/{book}/{page}/{col}/{slot}），没有
// "列出全部待判位"的批量浏览接口——Step5 四路证据本来就是按需产出，不是
// 预生成的列表，所以这里是一个查询工具，不是列表页。
export function RarePanel({ book }: { book: string }) {
  const [page, setPage] = useState('')
  const [col, setCol] = useState('')
  const [slot, setSlot] = useState('')
  const [sub, setSub] = useState('')
  const [candidates, setCandidates] = useState<RareCandidate[] | null>(null)
  const [msg, setMsg] = useState('')

  async function query() {
    const p = Number.parseInt(page, 10)
    const c = Number.parseInt(col, 10)
    const s = Number.parseInt(slot, 10)
    if (!p || !c || !s) { setMsg('页/列/格位都要填数字'); return }
    setMsg('查询中…')
    try {
      const d = await fetchRareOne(book, p, c, s, sub || undefined)
      setCandidates(d.candidates || [])
      setMsg(d.candidates?.length ? '' : '没有候选')
    } catch (e) {
      setMsg((e as Error).message)
      setCandidates(null)
    }
  }

  return (
    <div className="card">
      <h2>生僻字候选 <span className="muted">字体模板 + CNN 融合，输入字位坐标直接查</span></h2>
      <div className="rare-row">
        <label className="muted">页 <input value={page} onChange={(e) => setPage(e.target.value)} size={6} /></label>
        <label className="muted">列 <input value={col} onChange={(e) => setCol(e.target.value)} size={4} /></label>
        <label className="muted">格位 <input value={slot} onChange={(e) => setSlot(e.target.value)} size={4} /></label>
        <label className="muted">子列（夹注用，a/b，可空） <input value={sub} onChange={(e) => setSub(e.target.value)} size={3} /></label>
        <button onClick={query}>查候选</button>
        <span className="muted">{msg}</span>
      </div>
      <p className="muted rare-help">
        候选来自字体模板（4 套字体渲染 + 康熙字典白名单 + 字统网印/楷）与拆字 CNN
        融合（三源 RRF）。这一路只出候选、永不放行——库/OCR/上下文三路都给不出
        答案时才用得上，命中时中位名次 1。
      </p>
      {candidates && candidates.length > 0 && (
        <div className="rvrareout">
          {candidates.map((x, i) => (
            <div className="rvrrow" key={i}>
              <button className="rvpick rvrarepick" title={`${x.py ? x.py + ' · ' : ''}相似度 ${x.score} · ${x.font} · ${x.ids || '—'} · ${x.cp}`}>
                {x.char}
              </button>
              {x.std
                ? <b className="rvstd" title={`整理本里用的是这个字（${x.std_freq} 次）`}>→ {x.std}</b>
                : (x.freq ? <span className="rvin" title={`整理本里用过 ${x.freq} 次`}>【整】</span> : null)}
              <span className="rvgloss" title={x.gloss || ''}>{x.gloss || ''}</span>
              <a className="rvzi" href={x.zi} target="_blank" rel="noopener noreferrer">字统网</a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
