import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { STEPS, STEP5_SUBS } from '../steps'
import { listBooks } from '../api/registry'
import { getWorkspace, switchWorkspace } from '../api/workspace'
import type { WorkspaceState } from '../api/workspace'
import type { Book } from '../types/registry'
import { useBookCaps } from '../hooks/useBookCaps'

// 顶层布局：左侧导航。用户 2026-09-11 测试反馈 §1/§4 重排过一次：
// 换书下拉框置顶 → 分割线 → 总览 → Step0-9（Step5 四小步永久展开为二级
// 菜单，不用先点进 Step5 才看到）→ 分割线 → 运行 → 统计数据（原叫"评测"，
// 2026-09-11 改名——页面里真正在用的是判据体检/吞吐量这类统计数据，
// "评测器列表"反而是用得最少的一块，见 EvalsPage.tsx 头注）；
// 字形库／异体字库是独立于书之外的顶级栏目（§4），常驻侧边栏最下方，
// 不需要先选书。
export function AppLayout() {
  const { book } = useParams()
  const navigate = useNavigate()
  const [books, setBooks] = useState<Book[]>([])
  const [ws, setWs] = useState<WorkspaceState | null>(null)
  const [wsBusy, setWsBusy] = useState(false)
  const [wsErr, setWsErr] = useState('')
  // 侧边栏也按能力裁：点进去只会看到「这本书没开这一路」的子项就别列出来
  const { caps } = useBookCaps(book ?? '')

  useEffect(() => {
    listBooks().then(setBooks).catch(() => {})
    getWorkspace().then(setWs).catch(() => setWs(null))
  }, [])

  // 切工作区 = 改**本标签页**自己的偏好（sessionStorage），不通知服务端——
  // 下一个请求自然带上新的头。所以另一个标签页完全不受影响，两个页面可以
  // 同时在两个工作区上干活（用户 2026-09-15 定的形态）。
  async function onSwitchWorkspace(path: string) {
    if (!path || path === ws?.workspace) return
    setWsBusy(true); setWsErr('')
    try {
      switchWorkspace(path)                     // 纯前端，立即生效
      const [next, bs] = await Promise.all([getWorkspace(), listBooks()])
      setWs(next)
      setBooks(bs)
      // 跳回首页：原来那本书通常不属于新工作区，留在它的页面上只会看到一片空
      navigate('/')
    } catch (e) {
      setWsErr((e as Error).message)
    } finally {
      setWsBusy(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1><NavLink to="/">open-guji-cv 控制台</NavLink></h1>
        {ws && ws.available.length > 0 && (
          <label className="sidebar-book-select muted">工作区
            <select
              value={ws.workspace ?? ''}
              disabled={wsBusy}
              onChange={(e) => onSwitchWorkspace(e.target.value)}
            >
              {ws.available.map((w) => (
                <option key={w.path} value={w.path}>
                  {w.name}{w.books.length ? `（${w.books.length} 册）` : '（空）'}
                </option>
              ))}
            </select>
          </label>
        )}
        {wsErr && <p className="sidebar-ws-err">{wsErr}</p>}
        <label className="sidebar-book-select muted">册
          <select value={book ?? ''} onChange={(e) => e.target.value && navigate(`/${e.target.value}/`)}>
            <option value="" disabled>选一本书</option>
            {/* 册列表是「引擎仓 books/ ∪ 工作区 books/」的并集，于是每个工作区下都会
                看到别的工作区那些册（原图不在这儿、页数 0、产物全空）。分成两组，
                不属于本工作区的沉到「其他工作区」里，免得点开一片空白还以为跑挂了。 */}
            {books.filter((b) => b.in_workspace !== false)
                  .map((b) => <option key={b.id} value={b.id}>{b.id} · {b.title}</option>)}
            {books.some((b) => b.in_workspace === false) && (
              <optgroup label="其他工作区（本工作区无原图）">
                {books.filter((b) => b.in_workspace === false)
                      .map((b) => <option key={b.id} value={b.id}>{b.id} · {b.title}</option>)}
              </optgroup>
            )}
          </select>
        </label>
        {book ? (
          <>
            <hr className="sidebar-rule" />
            <nav className="sidebar-steps">
              <NavLink to={`/${book}/`} end>总览</NavLink>
              {STEPS.map((s) => (
                s.id === 'step5' ? (
                  <div key={s.id} className="sidebar-step5">
                    <NavLink to={`/${book}/step/step5/`} end>{s.title}</NavLink>
                    <div className="sidebar-step5-subs">
                      {STEP5_SUBS.filter((sub) => (
                        sub.id === 'ocr' ? caps.hasOcrCandidates
                          : sub.id === 'align-ref' ? caps.hasReference
                            : true
                      )).map((sub) => (
                        <NavLink key={sub.id} to={`/${book}/step/step5/${sub.id}/`}>{sub.title}</NavLink>
                      ))}
                    </div>
                  </div>
                ) : (
                  <NavLink key={s.id} to={`/${book}/step/${s.id}/`}>{s.title}</NavLink>
                )
              ))}
            </nav>
            <hr className="sidebar-rule" />
            <nav className="sidebar-cross">
              <NavLink to={`/${book}/runs/`}>运行</NavLink>
              <NavLink to={`/${book}/evals/`}>统计数据</NavLink>
            </nav>
          </>
        ) : (
          <p className="muted sidebar-hint">选一本书开始</p>
        )}
        <hr className="sidebar-rule" />
        <nav className="sidebar-libs">
          <NavLink to="/glyphlib/">字形库</NavLink>
          <NavLink to="/variantlib/">异体字库</NavLink>
        </nav>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
