import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useDeepLink } from '../hooks/useDeepLink'
import { ReviewPanel } from '../components/review/ReviewPanel'
import { CellLookupPanel } from '../components/review/CellLookupPanel'
import { BlockingCutlinePanel } from '../components/cutline/BlockingCutlinePanel'
import { StepLayout } from '../components/common/StepLayout'
import { loadSavedPageRange } from '../components/common/PageRangeSelector'

// D4：Step7 放行判定：定字裁决（v1 review tab 的核心）。
// 用户 2026-09-11 测试反馈 §4：异体用字账 / 组视图移出 Step7，升格成左侧栏
// 最下方独立的"异体字库"／"字形库"两个顶级栏目（见 GlyphLibraryPage /
// VariantLibraryPage）——理由是它们服务的是"整套书的字形/异体积累"，
// 不是"这本书 Step7 放行判定"这一件事，硬挂在某本书的 Step7 下不合适。
//
// 「切分裁决」板块（overview 2026-09-11 下发）：定字裁决下面的顺序闸只有一句
// 提示「⊘ N 位被顺序闸挡下」，没有入口——人得自己想起来去 Step3 页面处理，
// 两个面板不联动。这里在定字裁决**上方**直接挂 `BlockingCutlinePanel`，
// 只出顺序闸正在挡的那批多候选切点，裁完刷新一下定字裁决即可看到字卡解锁。
//
// 用户 2026-09-11 测试反馈：两个板块各自选页范围很割裂，且总默认 dev_set
// 记不住上次选择。改成本页顶部一个统一的页数输入框，控制两个板块，选择
// 存 localStorage（按 book 分开存，换册不会互相污染）。
//
// 2026-09-18：这份自写实现换成公共的 StepLayout + PageRangeSelector
// （计划书 §1.2「页范围唯一源」）。localStorage key 恰好完全一致
// （`guji-step7-pages:<book>` == `guji-<stepId>-pages:<book>` 当 stepId='step7'），
// 所以用户已存的选择不会丢。默认值仍是 dev_set——Step7 的卡是逐格的，
// 默认 all 会一次拉全书。

const STEP_ID = 'step7'

function Step7PageInner({ book }: { book: string }) {
  const deep = useDeepLink()
  const [reloadSignal, setReloadSignal] = useState(0)
  // 深链带了页号就用它当初始页范围（对勘报告「跳去改」进来的情形），
  // 否则照常读 localStorage。只影响初始值——进来之后改页范围不会被拽回去。
  // 深链带了页号就用它当初始页范围（对勘报告「跳去改」进来的情形），
  // 否则照常读 localStorage。只影响初始值——进来之后改页范围不会被拽回去。
  const [pageSel, setPageSel] = useState(() =>
    deep.active ? String(deep.page) : loadSavedPageRange(STEP_ID, book, 'dev_set'))

  // v1 的 onSubmitted 只刷新"审查批次台账"（harvest 面板，方案 §三 归 Step8），
  // 不影响 review 卡片本身；这里先留空实现占位，不能提交完就把刚裁的卡片
  // 列表清空重来。
  return (
    <StepLayout
      book={book} stepId={STEP_ID} pages={pageSel} onPagesChange={setPageSel}
      banner={deep.active ? (
        <div className="card" style={{ borderLeft: '3px solid #7a5c2e' }}>
          从对勘报告跳转而来：<b>{deep.id || `p${deep.page}`}</b>
          {deep.col !== null && <> · 第 {deep.col} 列</>}
          <span className="muted" style={{ marginLeft: '.6rem' }}>
            已把页范围设为 p{deep.page}；在下面「定字裁决」里找这一格改判
          </span>
        </div>
      ) : null}
      overview={<CellLookupPanel book={book} />}
      reviews={[
        { id: 'cutline', label: '切分裁决',
          node: <BlockingCutlinePanel book={book} pages={pageSel}
                                      onDecided={() => setReloadSignal((n) => n + 1)} /> },
        { id: 'decide', label: '定字裁决',
          node: <ReviewPanel book={book} pages={pageSel} onSubmitted={() => {}}
                             reloadSignal={reloadSignal} /> },
      ]}
    />
  )
}

// `key={book}` 让换册时整个内层组件树重新挂载，而不是手写"渲染期间同步
// 纠正 state"那套——之前那套在 book 首次从路由解析出来时触发了一次多余
// 的 pageSel 变化，被 ReviewPanel 内"pages 变化就 load()"的 effect 当成
// 真实的用户切页，造成"还没点载入就自动加载"（用户 2026-09-11 实测踩到）。
// key 重挂载更简单也更不容易出这类时序 bug。
export function Step7Page() {
  const { book = '' } = useParams()
  return <Step7PageInner key={book} book={book} />
}
