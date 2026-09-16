import { useEffect, useState } from 'react'
import { fetchStatus } from '../api/status'

// 各 Step 页面挂 ProductViewer 需要"这本书都有哪些页"——用状态矩阵的
// all_pages 就够，不必另开一个接口。
//
// `pageExpr` 可选：传了非默认表达式（如 PageRangeSelector 选出的 `3-6,9`）
// 就按后端筛选结果 `pages` 来，不再退回全量 `all_pages`——否则页面选择器
// 选了范围，ProductViewer 还是看全量页，选择器等于摆设。
export function usePages(book: string, pageExpr?: string): number[] {
  const [pages, setPages] = useState<number[]>([])
  useEffect(() => {
    setPages([])
    if (!book) return
    fetchStatus(book, 'keben_body_v2', pageExpr || 'dev_set')
      .then((s) => {
        if (pageExpr && pageExpr !== 'dev_set') {
          setPages((s.pages ?? []).map(Number))
          return
        }
        // all_pages 未设 GUJI_WORKSPACE 时可能是空数组（不是 null/undefined），
        // `??` 兜底不到——用长度判断，退回 pages（dev_set 那份至少非空）。
        setPages((s.all_pages?.length ? s.all_pages : s.pages ?? []).map(Number))
      })
      .catch(() => {})
  }, [book, pageExpr])
  return pages
}
