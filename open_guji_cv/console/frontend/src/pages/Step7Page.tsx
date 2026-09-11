import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ReviewPanel } from '../components/review/ReviewPanel'
import { CutlinePanel } from '../components/cutline/CutlinePanel'
import { ProductViewer } from '../components/ProductViewer'
import { usePages } from '../hooks/usePages'

// D4：Step7 放行判定：定字裁决（v1 review tab 的核心）。
// 用户 2026-09-11 测试反馈 §4：异体用字账 / 组视图移出 Step7，升格成左侧栏
// 最下方独立的"异体字库"／"字形库"两个顶级栏目（见 GlyphLibraryPage /
// VariantLibraryPage）——理由是它们服务的是"整套书的字形/异体积累"，
// 不是"这本书 Step7 放行判定"这一件事，硬挂在某本书的 Step7 下不合适。
//
// 「切分裁决」板块（overview 2026-09-11 下发）：定字裁决下面的顺序闸只有一句
// 提示「⊘ N 位被顺序闸挡下」，没有入口——人得自己想起来去 Step3 页面处理，
// 两个面板不联动。这里在定字裁决**上方**直接挂 `CutlinePanel scope="blocking"`，
// 只出顺序闸正在挡的那批多候选切点，裁完刷新一下定字裁决即可看到字卡解锁。
export function Step7Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)
  const [reloadSignal, setReloadSignal] = useState(0)

  // v1 的 onSubmitted 只刷新"审查批次台账"（harvest 面板，方案 §三 归 Step8），
  // 不影响 review 卡片本身；这里先留空实现占位，不能提交完就把刚裁的卡片
  // 列表清空重来。
  return (
    <div>
      <CutlinePanel book={book} scope="blocking" onDecided={() => setReloadSignal((n) => n + 1)} />
      <ReviewPanel book={book} onSubmitted={() => {}} reloadSignal={reloadSignal} />
      <ProductViewer book={book} step="seed_admit" pages={pages} />
    </div>
  )
}
