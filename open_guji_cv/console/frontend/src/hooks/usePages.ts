import { useEffect, useState } from 'react'
import { fetchStatus } from '../api/status'

// 各 Step 页面挂 ProductViewer 需要"这本书都有哪些页"——用状态矩阵的
// all_pages 就够，不必另开一个接口。
export function usePages(book: string): number[] {
  const [pages, setPages] = useState<number[]>([])
  useEffect(() => {
    setPages([])
    if (!book) return
    fetchStatus(book, 'keben_body_v2')
      // all_pages 未设 GUJI_WORKSPACE 时可能是空数组（不是 null/undefined），
      // `??` 兜底不到——用长度判断，退回 pages（dev_set 那份至少非空）。
      .then((s) => setPages((s.all_pages?.length ? s.all_pages : s.pages ?? []).map(Number)))
      .catch(() => {})
  }, [book])
  return pages
}
