// 板块① 页面选择器（03-Step页面统一设计.md §2.1）。从 Step7Page.tsx 原有的
// "页范围输入框 + localStorage 记忆"抽出来给所有 Step 用；localStorage key
// 按 `stepId` 分开存，Step 间不互相污染，按 `book` 分开存，换册不会互相污染。
//
// 默认值是 `all`（用户原话"默认所有"）——Step7 历史上默认 `dev_set` 是遗留，
// 这里不沿用；已经用 `dev_set` 惯了的 Step 可以在自己的任务书里说明理由后
// 传别的默认值给 `loadSavedPageRange`，组件本身不写死。
//
// 页范围表达式复用 `usePages`/`fetchStatus` 已支持的语法（`dev_set` / `body` /
// `all` / `3-6,9`），不在前端另造一套解析——展开成具体页码的活交给后端。

const KEY_PREFIX = 'guji-'

export function loadSavedPageRange(stepId: string, book: string, fallback = 'all'): string {
  if (!book) return fallback
  try {
    return localStorage.getItem(`${KEY_PREFIX}${stepId}-pages:${book}`) || fallback
  } catch {
    return fallback   // 隐私模式等 localStorage 不可用，退回默认
  }
}

export function saveSavedPageRange(stepId: string, book: string, v: string): void {
  if (!book) return
  try {
    localStorage.setItem(`${KEY_PREFIX}${stepId}-pages:${book}`, v)
  } catch { /* 隐私模式等，忽略 */ }
}

export interface PageRangeTypeFilter<T extends string = string> {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
}

export interface PageRangeSelectorProps {
  book: string
  stepId: string
  value: string
  onChange: (v: string) => void
  // 可选：按页面类型筛选（Step1 的"封面/职名页/正文"用得上），多数 Step 不传。
  typeFilter?: PageRangeTypeFilter
}

export function PageRangeSelector({ book, stepId, value, onChange, typeFilter }: PageRangeSelectorProps) {
  function handleChange(v: string) {
    onChange(v)
    saveSavedPageRange(stepId, book, v)
  }

  return (
    <div className="card">
      <label className="muted">
        页范围 <input value={value} onChange={(e) => handleChange(e.target.value)} size={12}
                     title="dev_set / body / all，或 3-6,9 这样的页号表达式；控制本页下面的板块" />
      </label>
      {typeFilter && (
        <label className="muted" style={{ marginLeft: '.8rem' }}>
          页面类型{' '}
          <select value={typeFilter.value} onChange={(e) => typeFilter.onChange(e.target.value)}>
            {typeFilter.options.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
      )}
    </div>
  )
}
