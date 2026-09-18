import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { STEPS, STEP5_SUBS, findStep } from '../steps'
import { listBooks } from '../api/registry'
import { getWorkspace } from '../api/workspace'
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
  const { ws: wsId = '', book } = useParams()
  // 工作区 id 是 URL 第一段，页面内所有链接都要带上它
  const at = (rest: string) => `/${encodeURIComponent(wsId)}${rest}`
  const navigate = useNavigate()
  const location = useLocation()
  const [books, setBooks] = useState<Book[]>([])
  const [ws, setWs] = useState<WorkspaceState | null>(null)
  // 切工作区现在只是一次 navigate，没有异步、也不会失败，忙碌/报错状态一并去掉
  // 侧边栏也按能力裁：点进去只会看到「这本书没开这一路」的子项就别列出来
  const { caps } = useBookCaps(book ?? '')

  useEffect(() => {
    listBooks().then(setBooks).catch(() => {})
    getWorkspace().then(setWs).catch(() => setWs(null))
  }, [])

  // 标签页标题：工作区 + Step 名。SPA 切路由不刷新 HTML，静态 <title> 只在
  // 整页刷新时生效一次，得在路由变化时手动写 document.title（用户 2026-09-17）。
  useEffect(() => {
    const stepId = location.pathname.match(/\/step\/([^/]+)\//)?.[1]
    const stepTitle = stepId ? findStep(stepId)?.title : undefined
    const parts = [wsId, stepTitle].filter(Boolean)
    document.title = parts.length ? `${parts.join(' · ')} - open-guji-cv 控制台` : 'open-guji-cv 控制台'
  }, [wsId, location.pathname])

  // 切工作区 = **换 URL 的第一段**，不存任何地方、也不通知服务端。
  // 跳到新工作区的首页：原来那本书通常不属于新工作区，带着册号跳过去只会
  // 看到一片空。整棵路由重挂，册列表/能力/产物自然全部重取。
  function onSwitchWorkspace(id: string) {
    if (!id || id === wsId) return
    navigate(`/${encodeURIComponent(id)}/`)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1><NavLink to={wsId ? at('/') : '/'}>open-guji-cv 控制台</NavLink></h1>
        {ws && ws.available.length > 0 && (
          <label className="sidebar-book-select muted">工作区
            <select
              value={wsId}
              onChange={(e) => onSwitchWorkspace(e.target.value)}
            >
              {ws.available.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.id}{w.books.length ? `（${w.books.length} 册）` : '（空）'}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="sidebar-book-select muted">册
          <select value={book ?? ''} onChange={(e) => e.target.value && navigate(at(`/${e.target.value}/`))}>
            <option value="" disabled>选一本书</option>
            {/* 2026-09-15 起册配置只读工作区（core/book.py），所以这个列表本来就
                只有本工作区的册，「其他工作区」那一组已无从产生，删掉。
                `in_workspace` 这道过滤留着：它判的是**原图目录在不在**，
                配置有、原图没下下来的册仍会被它挡住。 */}
            {books.filter((b) => b.in_workspace !== false)
                  .map((b) => <option key={b.id} value={b.id}>{b.id} · {b.title}</option>)}
          </select>
        </label>
        {book ? (
          <>
            <hr className="sidebar-rule" />
            <nav className="sidebar-steps">
              <NavLink to={at(`/${book}/`)} end>总览</NavLink>
              {STEPS.map((s) => (
                s.id === 'step5' ? (
                  <div key={s.id} className="sidebar-step5">
                    <NavLink to={at(`/${book}/step/step5/`)} end>{s.title}</NavLink>
                    <div className="sidebar-step5-subs">
                      {STEP5_SUBS.filter((sub) => (
                        sub.id === 'ocr' ? caps.hasOcrCandidates
                          : sub.id === 'align-ref' ? caps.hasReference
                            : true
                      )).map((sub) => (
                        <NavLink key={sub.id} to={at(`/${book}/step/step5/${sub.id}/`)}>{sub.title}</NavLink>
                      ))}
                    </div>
                  </div>
                ) : (
                  <NavLink key={s.id} to={at(`/${book}/step/${s.id}/`)}>{s.title}</NavLink>
                )
              ))}
            </nav>
            <hr className="sidebar-rule" />
            <nav className="sidebar-cross">
              <NavLink to={at(`/${book}/runs/`)}>运行</NavLink>
              <NavLink to={at(`/${book}/evals/`)}>统计数据</NavLink>
            </nav>
          </>
        ) : (
          <p className="muted sidebar-hint">选一本书开始</p>
        )}
        <hr className="sidebar-rule" />
        <nav className="sidebar-libs">
          <NavLink to={at('/glyphlib/')}>字形库</NavLink>
          <NavLink to={at('/variantlib/')}>异体字库</NavLink>
        </nav>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
