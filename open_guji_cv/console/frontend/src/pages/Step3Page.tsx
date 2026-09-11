import { useParams } from 'react-router-dom'
import { CutlinePanel } from '../components/cutline/CutlinePanel'
import { JiazhuPanel } from '../components/jiazhu/JiazhuPanel'
import { ProductViewer } from '../components/ProductViewer'
import { usePages } from '../hooks/usePages'

// D3：Step3 逐字切分。切线（v1 cutline tab）与夹注（v1 jiazhu tab）按方案 §三
// 都归 Step3——都是 row_segment 的一部分（jiazhu_split 是 Step3 的子模块，
// 折线缝 utils/seam.py 同样服务 row_segment）。
export function Step3Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)
  return (
    <div>
      <CutlinePanel book={book} />
      <JiazhuPanel book={book} />
      <ProductViewer book={book} step="row_segment" pages={pages} />
    </div>
  )
}
