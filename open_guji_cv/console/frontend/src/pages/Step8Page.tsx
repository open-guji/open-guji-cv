import { HarvestPanel } from '../components/feedback/HarvestPanel'

// D5：Step8 落库反馈。收割消费 + 审查批次台账 + 金标分片表（v1 review tab 里
// 除定字裁决/体检之外的第三块），方案 §三：文档写得很明确，无歧义。
export function Step8Page() {
  return (
    <div>
      <HarvestPanel />
    </div>
  )
}
