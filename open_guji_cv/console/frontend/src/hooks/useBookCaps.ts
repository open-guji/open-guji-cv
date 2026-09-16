import { useEffect, useState } from 'react'
import { getBook } from '../api/registry'
import { capsOf } from '../capabilities'
import type { Caps } from '../capabilities'
import type { Book } from '../types/registry'

/** 这册书的版式声明 + 由它推出的面板可见性。
 *
 * 每个 Step 页都要这两样（选后端 step id、决定哪些面板出现），原先各页自己
 * `useState` + `getBook`，抄了四五份；换工作区后还得各自记得重取。收成一个钩子。
 */
export function useBookCaps(book: string): { meta: Book | null; caps: Caps } {
  const [meta, setMeta] = useState<Book | null>(null)

  useEffect(() => {
    let alive = true
    const load = () => {
      if (!book) { setMeta(null); return }
      getBook(book).then((b) => { if (alive) setMeta(b ?? null) })
        .catch(() => { if (alive) setMeta(null) })
    }
    load()
    // 换工作区 = 换 URL，整棵路由重挂，这个 effect 自然重跑，不必再听事件
    return () => { alive = false }
  }, [book])

  return { meta, caps: capsOf(meta) }
}
