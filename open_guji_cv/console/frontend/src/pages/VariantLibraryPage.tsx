import { VariantBookPanel } from '../components/variants/VariantBookPanel'

// 用户 2026-09-11 测试反馈 §4：异体字库——我们积累的一套异体字映射库，
// 把"本书用字账"放进去。独立于书之外的顶级栏目（/variantlib/）。
// VariantBookPanel 本身按"套"（edition）维度查询，不依赖某一本书，
// 不需要额外的书选择器。
export function VariantLibraryPage() {
  return (
    <div>
      <VariantBookPanel />
    </div>
  )
}
