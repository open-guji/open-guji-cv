import { useState } from 'react'
import { BorderReviewPanel } from './BorderReviewPanel'
import { HeadRaisePanel } from './HeadRaisePanel'

// 抬头标注：页级 + 列级两个 tab 共用一张卡（用户 2026-09-12 定）。
//
// 两级本来就是同一件事的粗细两档——页级粗筛找出抬头页，列级只对判 yes 的页
// 精标格数。原先页级在 Step1 页、列级在 Step3 页，人要来回跳两个 Step 才能
// 走完一轮。抬头**终判在 Step3**，所以两级一起放 Step3。
//
// 页级那一档仍然走 BorderReviewPanel 的 kind="head"（形状是"一图 + 一排按钮"，
// 没必要为了搬家重写），列级走自己的 HeadRaisePanel（一卡三问）。

type Level = 'head' | 'headcol'

export function HeadRaiseCard({ book, pages }: { book: string; pages?: string }) {
  const [level, setLevel] = useState<Level>('headcol')
  return (
    <>
      <div className="card">
        <h2>抬头标注 <span className="muted">页级粗筛 → 列级精标，两档都在这里</span></h2>
        <p className="muted br-howto">
          先用<b>页级</b>快速扫全册、找出有抬头的页（便宜，一页一张卡）；
          再切到<b>列级</b>，只对判"有抬头"的页逐列精标格数与首字完整性。
          页级量的是 Step1 抬头框探测器的召回率，列级补的是 <code>n_raised</code>
          的逐列真值——两个分片分开存，口径不同不能混。
        </p>
        <div className="seg" style={{ display: 'inline-flex', gap: '.3rem' }}>
          <button aria-pressed={level === 'head'} onClick={() => setLevel('head')}>页级抬头标注</button>
          <button aria-pressed={level === 'headcol'} onClick={() => setLevel('headcol')}>列级抬头精标</button>
        </div>
      </div>
      {level === 'head' ? <BorderReviewPanel book={book} kind="head" pages={pages} />
                        : <HeadRaisePanel book={book} pages={pages} />}
    </>
  )
}
