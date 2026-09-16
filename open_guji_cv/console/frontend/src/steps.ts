// 管线九步的编号与标题，对齐 overview 仓 项目进展/图片初步数字化/流程与模块.md
// 与 进度/Step*-*/ 目录名——不另编号（方案 §二）。
// Step9（结果整理）产物形态未定，方案原定本轮不开路由，用户 2026-09-11 改口
// 「也加上，虽然暂时空的」——纳入导航，backendIds 留空（没有对应的后端 Step）。

export interface StepMeta {
  id: string
  title: string
  /** 后端 core/step.py 里对应的 step id 前缀，用于关联 /api/steps 的产物；
   * 没有代码对应的（Step0/1/2/4 现在控制台没有面板）留空数组。
   * **一个 Step 页可以对多条链**：刻本链与现代印刷链在 Step1–3 是不同的
   * step id（见下），用 `backendIdFor(meta, edition)` 按册书取那一个。*/
  backendIds: string[]
  /** 现代印刷链（pipelines/modern_body.yaml）在这一步的 step id，
   * 缺省 = 与刻本链同名。*/
  modernId?: string
}

// 现代印刷链（pipelines/modern_body.yaml）与刻本链一一对位，占同一个 Step 页：
// line_detect ↔ border_detect（Step1）、column_crop ↔ column_warp（Step2）、
// row_segment_runs ↔ row_segment（Step3）。同一页下两条链的产物种类相同
// （line_index 是 Step1 的新种类），叠图 render/overlay.py 两边都认。
export const STEPS: StepMeta[] = [
  { id: 'step0', title: 'Step0 预清理', backendIds: ['preclean'] },
  { id: 'step1', title: 'Step1 边框界行', backendIds: ['border_detect', 'line_detect'], modernId: 'line_detect' },
  { id: 'step2', title: 'Step2 单列射影', backendIds: ['column_warp', 'column_crop'], modernId: 'column_crop' },
  { id: 'step3', title: 'Step3 逐字切分', backendIds: ['row_segment', 'row_segment_runs'], modernId: 'row_segment_runs' },
  { id: 'step4', title: 'Step4 字框收缩', backendIds: ['cell_shrink'] },
  // 用户 2026-09-11 测试反馈 §5：Step5 改名"字符识别"（只改这一级标题，
  // 四个小步 5-a/5-b/5-c/5-d 名字不变）
  { id: 'step5', title: 'Step5 字符识别', backendIds: [] },
  { id: 'step6', title: 'Step6 上下文裁决', backendIds: ['context_decide'] },
  { id: 'step7', title: 'Step7 放行判定', backendIds: ['seed_admit'] },
  { id: 'step8', title: 'Step8 落库反馈', backendIds: [] },
  { id: 'step9', title: 'Step9 结果整理', backendIds: [] },
]

// Step5 四路，方案 §二：/<book>/step/step5/<sub>/
export interface Step5Sub {
  id: string
  title: string
}

export const STEP5_SUBS: Step5Sub[] = [
  { id: 'glyph-match', title: '5-a 字形库匹配' },
  { id: 'rare', title: '5-b 生僻字候选' },
  { id: 'ocr', title: '5-c OCR 候选' },
  { id: 'align-ref', title: '5-d 整理本匹配' },
]

export function findStep(id: string): StepMeta | undefined {
  return STEPS.find((s) => s.id === id)
}

/** 这册书在这一步跑的后端 step id：现代印刷本（Book.edition === 'modern'）
 * 走 `modernId`，其余走 `backendIds[0]`。返回 undefined = 这一步没有后端 Step。 */
export function backendIdFor(meta: StepMeta | undefined, edition?: string): string | undefined {
  if (!meta) return undefined
  if (edition === 'modern' && meta.modernId) return meta.modernId
  return meta.backendIds[0]
}

/** 闸1（边框界行出口）的 id：两条链的 Step id 不同，产物 kind 同名。
 * 写死 border_detect_gate 会让现代印刷本的 Step1 页拿不到页型统计，
 * 整页显示「无产物 80」——产物其实都在（2026-09-15）。 */
export function gate1IdFor(edition?: string): string {
  return edition === 'modern' ? 'line_detect_gate' : 'border_detect_gate'
}

/** 按后端 core/step.py 的 step id（比如 border_detect）反查前端 Step 页面。 */
export function findStepByBackendId(backendId: string): StepMeta | undefined {
  return STEPS.find((s) => s.backendIds.includes(backendId))
}
