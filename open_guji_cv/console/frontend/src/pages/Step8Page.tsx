import { useParams } from 'react-router-dom'
import { CollateDesk } from '../components/step8/CollateDesk'
import { HarvestPanel } from '../components/feedback/HarvestPanel'

// Step8 对勘与复核（2026-09-22 扩：原本只有 HarvestPanel）。
//
// 用户判断：「step8 其实没有什么内容，这些入库的决定应该是 step7 顺便就做了的」
// ——属实。三个落库出口的执行体全在 Step7 的裁决提交里顺手做掉了。真正缺位置的
// 是**全局复核**：Step7 只知道「机器确不确定」，不知道「机器对不对」，后者只有
// 与独立校对本逐字对勘能答。
//
// 落库台账（HarvestPanel）降为次要，排在复核之后：它是 Step7 的账，不是一步。
export function Step8Page() {
  const { book = '' } = useParams()
  return (
    <div>
      <CollateDesk book={book} />
      <details className="s8-ledger">
        <summary>落库台账（Step7 裁决的三个出口）</summary>
        <HarvestPanel />
      </details>
    </div>
  )
}
