import { CellReviewPanel } from '../components/cell-review/CellReviewPanel'

// 格级审阅页（GUJI-364b，2026-10）：通用单字特写，逐格判「这格是哪个字」，可导出 TSV。
// 挂在工作区下：`/<ws>/cell-review/`。候选清单来自工作区 feedback/candidates。
export function CellReviewPage() {
  return (
    <div>
      <h2>格级审阅 <span className="muted">逐格判是哪个字</span></h2>
      <CellReviewPanel />
    </div>
  )
}
