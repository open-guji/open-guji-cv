import { useState } from 'react'
import { loadSavedPageRange, saveSavedPageRange } from '../components/common/PageRangeSelector'

// 各面板自己的"页 <input>"（跟板块①统一的 PageRangeSelector 不是一回事——
// 那些是子面板各自维护的页范围，互不联动）也要记住上次的选择，用同一套
// localStorage 原语（load/saveSavedPageRange），但 `id` 必须是这个输入框
// 唯一的身份。用户 2026-09-12 定：「不同的页码选择器 id 应该不同，不要
// 共享」——同一个组件在不同 tab 下复用时（如 BorderReviewPanel 的
// cols/head/outer/colborder 四个 kind），调用方要把 kind 拼进 id，
// 不能让四个 tab 抢同一个 localStorage key。
export function usePersistedPages(id: string, book: string, fallback = 'dev_set') {
  const [pages, setPagesState] = useState(() => loadSavedPageRange(id, book, fallback))
  const [loadedBook, setLoadedBook] = useState(book)
  if (book !== loadedBook) {
    setLoadedBook(book)
    setPagesState(loadSavedPageRange(id, book, fallback))
  }
  function setPages(v: string) {
    setPagesState(v)
    saveSavedPageRange(id, book, v)
  }
  return [pages, setPages] as const
}
