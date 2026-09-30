// 候选生成与键位表，抽成纯函数，对应 v1 review.js 的 rvCandList / rvKeyList。
// 候选顺序（用户 2026-09-06）：① 整理本用字 ② 库最佳 ③ 生僻字算法 ④⑤ 库次选；
// 借库书开了 first_pick 时在 ① 之后插「CNN／融合」首选（2026-09-27）；
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
  // 借库书（`c.first` 只在书 yaml 开了 `params.review.first_pick` 时有）：CNN 原型首选
  // 排在整理本之后、像素库首选之前——借来的库上像素排名是歪的（全唐文人裁难例首选
  // 52.4%，CNN 原型 94%），默认该按 CNN 那一路。同字会与 库/形 合并成一个按钮。
  if (c.first?.char) {
    const f = c.first
    list.push({
      ch: f.char!, src: f.mode === 'cnn' ? 'CNN' : '融合',
      note: (f.mode === 'cnn' ? 'CNN 原型检索首选' : '像素与 CNN 名次融合（RRF）首选')
        + (f.agree === true ? '（两路一致）' : f.agree === false ? `（两路不一致：像素 ${f.pixel}，CNN ${f.cnn}）` : ''),
    })
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
