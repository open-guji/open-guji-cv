import { useParams } from 'react-router-dom'

/** 给页面内部的链接补上工作区前缀。
 *
 * 工作区 id 是 URL 第一段（`/<ws>/<book>/…`），所以页面里所有 `to=` / `navigate()`
 * 都得带上它，否则一点就跳出工作区、掉回根路径的选择页。
 * 写成钩子而不是各页自己拼，是因为漏一个不会报错——只会在点下去那一刻才发现。
 */
export function useWsPath(): (rest: string) => string {
  const { ws = '' } = useParams()
  return (rest: string) => `/${encodeURIComponent(ws)}${rest.startsWith('/') ? rest : '/' + rest}`
}
