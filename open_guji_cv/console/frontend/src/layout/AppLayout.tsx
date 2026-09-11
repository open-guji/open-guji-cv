import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { STEPS, STEP5_SUBS } from '../steps'
import { listBooks } from '../api/registry'
import type { Book } from '../types/registry'

// 顶层布局：左侧导航。用户 2026-09-11 测试反馈 §1/§4 重排过一次：
// 换书下拉框置顶 → 分割线 → 总览 → Step0-9（Step5 四小步永久展开为二级
// 菜单，不用先点进 Step5 才看到）→ 分割线 → 运行 → 评测；字形库／异体字库
// 是独立于书之外的顶级栏目（§4），常驻侧边栏最下方，不需要先选书。
export function AppLayout() {
  const { book } = useParams()
  const navigate = useNavigate()
  const [books, setBooks] = useState<Book[]>([])

  useEffect(() => {
    listBooks().then(setBooks).catch(() => {})
  }, [])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1><NavLink to="/">open-guji-cv 控制台</NavLink></h1>
        <label className="sidebar-book-select muted">册
          <select value={book ?? ''} onChange={(e) => e.target.value && navigate(`/${e.target.value}/`)}>
            <option value="" disabled>选一本书</option>
            {books.map((b) => <option key={b.id} value={b.id}>{b.id} · {b.title}</option>)}
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
                      {STEP5_SUBS.map((sub) => (
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
              <NavLink to={`/${book}/evals/`}>评测</NavLink>
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
