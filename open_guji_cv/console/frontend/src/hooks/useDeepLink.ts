import { useSearchParams } from 'react-router-dom'

// 深链：从对勘报告（Step9-9.3）跳到某一格 / 某一列去改。
//
// 约定（overview 仓 Step9-结果整理/04-与整理本对比校验.md §二·4）：
//   字符类差异 → /<book>/step/step7/?id=vol02:33:1:7
//   增删/列结构 → /<book>/step/step3/?page=33&col=1
//
// 为什么用 query 不用新路由：`/:book/step/:step/` 这条路由已经在了，深链只是
// 「进这一页时先定位到哪」，不是另一种页面。加路由段会让 Step3/Step7 各多一条
// 只为跳转存在的分支。
//
// **只作用于初始页范围**，不接管后续交互：用户进来后自己改页范围、切板块都照常，
// 不会被 URL 里的旧参数拽回去（那种「URL 说了算」的写法在 v1 踩过——改完一个
// 格子想看隔壁页，一刷新又跳回原处）。
export interface DeepLink {
  /** 报告给的字位 id `book:page:col:slot[a|b]`，Step7 用它高亮某张卡 */
  id: string | null
  /** 目标页号；`id` 里能解析出来时优先用它 */
  page: number | null
  /** 目标列号，Step3 用 */
  col: number | null
  /** 有没有携带定位信息——false 时各页照常走 localStorage 的默认页范围 */
  active: boolean
}

/** 从 `?id=` / `?page=&col=` 解析定位信息。两种写法都支持，`id` 优先。 */
export function useDeepLink(): DeepLink {
  const [sp] = useSearchParams()
  const id = sp.get('id')
  let page: number | null = null
  let col: number | null = null

  if (id) {
    // book:page:col:slot[a|b] —— 只取 page/col，slot 留给页面自己去匹配卡片
    const parts = id.split(':')
    if (parts.length >= 3) {
      const p = Number(parts[1])
      const c = Number(parts[2])
      if (Number.isFinite(p)) page = p
      if (Number.isFinite(c)) col = c
    }
  }
  if (page === null) {
    const p = Number(sp.get('page'))
    if (sp.get('page') !== null && Number.isFinite(p)) page = p
  }
  if (col === null) {
    const c = Number(sp.get('col'))
    if (sp.get('col') !== null && Number.isFinite(c)) col = c
  }

  return { id, page, col, active: page !== null }
}
