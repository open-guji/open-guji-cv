import { useEffect, useState } from 'react'
import { fetchGateSummary } from '../../api/evals'
import type { GateSummaryPageRow, GateSummaryResponse } from '../../types/evals'
import '../evals/evals.css'

// 板块②：进度摘要 + 闸判据，各 Step 页面共用（overview 03-Step页面统一设计.md
// §2.2）。从 components/evals/GateSummaryPanel.tsx 拆出通用部分——那个组件
// 服务评测页，硬编码了闸切换 tab；这里给单个 Step 页面用，闸 id 由调用方定死，
// 不需要切换。
//
// 兼容两种数据源：已收闸的传 `gateId`（走 gate_summary 现成产物），未收闸的
// 传 `customMetrics`（把散在算法里的判据数字摆进统一卡片形状，不等真闸落地）。
export interface CustomMetric {
  label: string
  value: string
  tone?: 'ok' | 'bad'
}

export interface TypeBreakdownItem {
  label: string
  count: number
  /** 该类型对应的页码，已折叠成连续区间（如 "12-15"）；用于总览一眼看出
   * 这批页里哪几页是这个类型，不用逐页翻。 */
  ranges?: string
}

/** 把一组页码折叠成连续区间的逗号列表，如 [1,2,3,7,9,10] → "1-3, 7, 9-10"。 */
export function foldPageRanges(pages: number[]): string {
  const sorted = [...pages].sort((a, b) => a - b)
  const parts: string[] = []
  let start = 0
  for (let i = 0; i <= sorted.length; i++) {
    if (i === sorted.length || sorted[i] !== sorted[i - 1] + 1) {
      if (i > start) {
        const a = sorted[start], b = sorted[i - 1]
        parts.push(a === b ? `${a}` : `${a}-${b}`)
      }
      start = i
    }
  }
  return parts.join(', ')
}

export interface ProgressGatePanelProps {
  book: string
  title: string
  gateId?: string
  pages?: string
  customMetrics?: CustomMetric[]
  typeBreakdown?: TypeBreakdownItem[]
}

export function ProgressGatePanel({ book, title, gateId, pages, customMetrics, typeBreakdown }: ProgressGatePanelProps) {
  const [d, setD] = useState<GateSummaryResponse | null>(null)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!gateId || !book) { setD(null); return }
    setMsg('统计中…')
    fetchGateSummary(book, gateId, pages)
      .then((r) => { setD(r); setMsg('') })
      .catch((e) => { setD(null); setMsg('统计失败：' + (e as Error).message) })
  }, [book, gateId, pages])

  const blocked = d ? d.pages.filter((p) => p.status === 'page_blocked') : []
  const missing = d ? d.pages.filter((p) => p.status === 'missing') : []
  const ok = d ? d.pages.filter((p) => p.status === 'ok') : []
  const flagged = d ? d.pages.filter((p) => (p.flags?.length ?? 0) > 0) : []
  // 闸2/闸3 2026-09-12 起把「闸1判定 skip」的页级 reject 写成 L0 开头——
  // 从「整页被拦」里单独拆出来，别让"跳过的非正文页"和"真正探测/切分
  // 失败"混在一个数字里，前者是预期行为不是错误。
  const isSkipBlocked = (p: GateSummaryPageRow) => (p.page_reject || []).some((r) => r.startsWith('L0：'))
  // 闸3 2026-09-13 起单列「版式未支持」（职名/目录：每列字数非版式格数且逐列
  // 不同，21 格先验必然无解）——非故障，同样不该混进「整页被拦（异常）」。
  // 判定由后端落盘（`unsupported_layout`），这里只读不算；老产物没有这个字段
  // 时退回按 L0u 前缀认，免得没重跑闸的册子显示成异常。
  const isUnsupported = (p: GateSummaryPageRow) =>
    p.unsupported_layout ?? (p.page_reject || []).some((r) => r.startsWith('L0u'))
  const skipBlocked = blocked.filter((p) => isSkipBlocked(p) && !isUnsupported(p))
  const unsupported = blocked.filter(isUnsupported)
  const realBlocked = blocked.filter((p) => !isSkipBlocked(p) && !isUnsupported(p))

  return (
    <div className="card">
      <h2>{title}</h2>

      {typeBreakdown && typeBreakdown.length > 0 && (
        <div className="counts" style={{ marginBottom: '.6rem' }}>
          {typeBreakdown.map((t) => (
            <span key={t.label} className="qchip" title={t.ranges || undefined}>
              {t.label}<b>{t.count}</b>
              {t.ranges && <span className="muted"> （{t.ranges}）</span>}
            </span>
          ))}
        </div>
      )}

      {customMetrics && customMetrics.length > 0 && (
        <div className="qgrid" style={{ marginBottom: gateId ? '1rem' : 0 }}>
          {customMetrics.map((m) => (
            <div key={m.label}>
              <div className="qk">{m.label}</div>
              <div className={`qv ${m.tone === 'bad' ? 'qbad' : m.tone === 'ok' ? 'qok' : ''}`}>{m.value}</div>
            </div>
          ))}
        </div>
      )}

      {gateId && !d && <div className="muted">{msg || '点击加载闸数据'}</div>}
      {gateId && d && (
        <div className="qgrid">
          <div>
            <div className="qk">页级状态</div>
            <div className={`qv ${realBlocked.length ? 'qbad' : 'qok'}`}>{ok.length}/{d.pages.length}</div>
            <div className="qs">
              过闸 {ok.length} · 非正文跳过 {skipBlocked.length} ·
              {unsupported.length > 0 && <> 版式未支持 {unsupported.length} · </>}
              整页被拦（异常）{realBlocked.length} ·
              无产物 {missing.length} · 带 flag {flagged.length}
            </div>
            {realBlocked.length > 0 && (
              <div className="qerr">
                {realBlocked.slice(0, 8).map((p) => (
                  <div key={p.page}>p{p.page}：{(p.page_reject || []).join('；')}</div>
                ))}
                {realBlocked.length > 8 && <div className="qs">…另 {realBlocked.length - 8} 页</div>}
              </div>
            )}
            {skipBlocked.length > 0 && (
              <div className="qs" style={{ marginTop: '.4rem' }}>
                非正文跳过（页型判定，非异常）：{foldPageRanges(skipBlocked.map((p) => p.page))}
              </div>
            )}
            {unsupported.length > 0 && (
              <div className="qs" style={{ marginTop: '.4rem' }}>
                版式未支持（职名/目录类，每列字数非版式格数且逐列不同，非异常）：
                {foldPageRanges(unsupported.map((p) => p.page))}
              </div>
            )}
          </div>
          {flagged.length > 0 && (
            <div>
              <div className="qk">flag 级提示（不拦，供复核）</div>
              <div className="qerr" style={{ color: 'var(--ink-2)' }}>
                {flagged.slice(0, 8).map((p) => (
                  <div key={p.page}>p{p.page}：{(p.flags || []).join('；')}</div>
                ))}
                {flagged.length > 8 && <div className="qs">…另 {flagged.length - 8} 页</div>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
