// 候选生成与键位表，抽成纯函数，对应 v1 review.js 的 rvCandList / rvKeyList。
// 候选顺序（用户 2026-09-06）：① 整理本用字 ② 库最佳 ③ 生僻字算法 ④⑤ 库次选；
// OCR 只留在证据行末尾。同一个字从两路来就并成一个按钮（键位都指向它）。
import type { RareCandidate, ReviewCard } from '../../types/review'

export interface CandItem {
  ch: string
  src: string
  note: string
  nokey?: boolean
}

export function candList(c: ReviewCard, rare: RareCandidate[] | undefined): CandItem[] {
  const db = (c.db?.candidates || []).slice(0, 3)
  const list: CandItem[] = []
  if (c.ref?.char) {
    list.push({
      ch: c.ref.char, src: '整理本',
      note: '整理本在这一位印的字' + (c.ref.op === 'replace' ? '（对齐段是 replace，位置可能错开一两格）' : ''),
    })
    if (c.ref.form) {
      list.push({ ch: c.ref.form, src: '刻本惯用', nokey: true, note: `整理本印「${c.ref.char}」时本书惯刻这个形（用字账）` })
    }
  }
  if (db[0]) list.push({ ch: db[0][0], src: '库', note: '字形库最佳匹配 cov ' + db[0][1] })
  if (rare && rare[0]) list.push({ ch: rare[0].char, src: '形', note: '生僻字算法（字体模板+CNN）相似度 ' + rare[0].score })
  else list.push({ ch: '', src: '形', note: rare ? '生僻字算法没给出候选' : '生僻字候选加载中…' })
  db.slice(1).forEach(([ch, cov]) => list.push({ ch, src: '库', note: '库次选 cov ' + cov }))
  return list
}

export interface KeyItem {
  ch: string
  keys: number[]
  srcs: string[]
  note: string
  nokey: boolean
}

export function keyList(c: ReviewCard, rare: RareCandidate[] | undefined): KeyItem[] {
  const out: KeyItem[] = []
  const byCh: Record<string, KeyItem> = {}
  let key = 0
  for (const x of candList(c, rare)) {
    if (x.ch && byCh[x.ch]) {
      byCh[x.ch].srcs.push(x.src)
      if (!x.nokey) byCh[x.ch].keys.push(++key)
      continue
    }
    const e: KeyItem = { ch: x.ch, srcs: [x.src], keys: x.nokey ? [] : [++key], note: x.note, nokey: !!x.nokey }
    if (x.ch) byCh[x.ch] = e
    out.push(e)
  }
  return out
}
