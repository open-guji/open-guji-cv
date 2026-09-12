import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ReviewPanel } from '../components/review/ReviewPanel'
import { BlockingCutlinePanel } from '../components/cutline/BlockingCutlinePanel'
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
// 两个面板不联动。这里在定字裁决**上方**直接挂 `BlockingCutlinePanel`，
// 只出顺序闸正在挡的那批多候选切点，裁完刷新一下定字裁决即可看到字卡解锁。
//
// 用户 2026-09-11 测试反馈：两个板块各自选页范围很割裂，且总默认 dev_set
// 记不住上次选择。改成本页顶部一个统一的页数输入框，控制两个板块，选择
// 存 localStorage（按 book 分开存，换册不会互相污染）。
const PAGES_KEY_PREFIX = 'guji-step7-pages:'

function loadSavedPages(book: string): string {
  if (!book) return 'dev_set'
  try {
    return localStorage.getItem(PAGES_KEY_PREFIX + book) || 'dev_set'
  } catch {
    return 'dev_set'   // 隐私模式等 localStorage 不可用，退回默认
  }
}

export function Step7Page() {
  const { book = '' } = useParams()
  const pages = usePages(book)
  const [reloadSignal, setReloadSignal] = useState(0)
  // 用 book 做 key 惰性初始化——首次渲染直接拿到该册上次的选择，不必等一次
  // effect 才把状态从 dev_set 纠正过去（避免一次多余的级联渲染/网络请求）。
  const [pageSel, setPageSel] = useState(() => loadSavedPages(book))
  const [loadedBook, setLoadedBook] = useState(book)
  if (book !== loadedBook) {
    // 路由切了册（同一个 Step7Page 实例，book 参数变了）：渲染期间同步纠正，
    // 而不是走 effect——这正是 React 官方推荐的"响应 prop 变化重置 state"
    // 写法，比 useEffect 里 setState 少一次渲染。
    setLoadedBook(book)
    setPageSel(loadSavedPages(book))
  }

  function setPages(v: string) {
    setPageSel(v)
    if (book) {
      try { localStorage.setItem(PAGES_KEY_PREFIX + book, v) } catch { /* 隐私模式等，忽略 */ }
    }
  }

  // v1 的 onSubmitted 只刷新"审查批次台账"（harvest 面板，方案 §三 归 Step8），
  // 不影响 review 卡片本身；这里先留空实现占位，不能提交完就把刚裁的卡片
  // 列表清空重来。
  return (
    <div>
      <div className="card">
        <label className="muted">
          页范围 <input value={pageSel} onChange={(e) => setPages(e.target.value)} size={12}
                       title="dev_set / body / all，或 3-6,9 这样的页号表达式；下面两个板块共用这个范围" />
        </label>
        <span className="muted" style={{ marginLeft: '.6rem' }}>控制下面「切分裁决」与「定字裁决」两个板块，记住你上次的选择</span>
      </div>
      <BlockingCutlinePanel book={book} pages={pageSel} onDecided={() => setReloadSignal((n) => n + 1)} />
      <ReviewPanel book={book} pages={pageSel} onSubmitted={() => {}} reloadSignal={reloadSignal} />
      <ProductViewer book={book} step="seed_admit" pages={pages} />
    </div>
  )
}
