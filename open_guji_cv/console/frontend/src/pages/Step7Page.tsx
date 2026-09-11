import { useParams } from 'react-router-dom'
import { ReviewPanel } from '../components/review/ReviewPanel'
import { ProductViewer } from '../components/ProductViewer'
import { usePages } from '../hooks/usePages'

// D4：Step7 放行判定：定字裁决（v1 review tab 的核心）。
// 用户 2026-09-11 测试反馈 §4：异体用字账 / 组视图移出 Step7，升格成左侧栏
// 最下方独立的"异体字库"／"字形库"两个顶级栏目（见 GlyphLibraryPage /
// VariantLibraryPage）——理由是它们服务的是"整套书的字形/异体积累"，
// 不是"这本书 Step7 放行判定"这一件事，硬挂在某本书的 Step7 下不合适。
export function Step7Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)

  // v1 的 onSubmitted 只刷新"审查批次台账"（harvest 面板，方案 §三 归 Step8），
  // 不影响 review 卡片本身；这里先留空实现占位，不能提交完就把刚裁的卡片
  // 列表清空重来。
  return (
    <div>
      <ReviewPanel book={book} onSubmitted={() => {}} />
      <ProductViewer book={book} step="seed_admit" pages={pages} />
    </div>
  )
}
