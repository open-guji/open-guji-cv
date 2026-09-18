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

//: 后端 `resolve_pages` / 各 cases 接口支持的取值。此前前端只在 title 里提了
//: 三种，`body` / `list:` / `drift` 这些**后端早就支持、前端从没暴露**，
//: 等于藏起来的功能（《计划书-控制台四板块统一》§1.2）。
export const PAGE_RANGE_PRESETS: { value: string; label: string; hint: string }[] = [
  { value: 'all', label: 'all — 全书', hint: '整册所有页' },
  { value: 'dev_set', label: 'dev_set — 分层小页集', hint: '册 yaml 里固定的那批，历史数字都挂在它上面' },
  { value: 'body', label: 'body — 正文页', hint: 'page-type 判为正文的页（跳过封面/职名/目录）' },
  { value: 'drift', label: 'drift — 产物过期的', hint: '上游重跑后金标坐标系可能已失准的那批' },
]

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

  // 预设值用下拉快选，手输框仍在——`list:<名字>` / `3-6,9` / `cells:<坐标>`
  // 这类要打字，不能只给下拉。
  const preset = PAGE_RANGE_PRESETS.find((p) => p.value === value)?.value ?? ''

  return (
    <div className="card">
      <label className="muted">
        页范围 <input value={value} onChange={(e) => handleChange(e.target.value)} size={12}
                     title="dev_set / body / all / drift，或 3-6,9 页号表达式、list:<名字>、cells:<坐标表>；控制本页下面所有板块" />
      </label>
      <select className="muted" value={preset} style={{ marginLeft: '.4rem' }}
              onChange={(e) => e.target.value && handleChange(e.target.value)}
              title="常用取值；list: 与页号表达式请直接在左边输入框打字">
        <option value="">快选…</option>
        {PAGE_RANGE_PRESETS.map((p) => (
          <option key={p.value} value={p.value} title={p.hint}>{p.label}</option>
        ))}
      </select>
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
