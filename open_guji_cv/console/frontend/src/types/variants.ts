// 对应 GET /api/variants/book 与 /api/variants/groups，字段照
// v1 static/js/panels/variants.js / groups.js 的用法反推（原样复用后端契约）。

export interface VariantFormBook {
  products: number
  db: number
  align: number
  human?: number
}

export interface VariantForm {
  book: VariantFormBook
  ref: number
  tier?: string
}

export interface VariantGroup {
  canonical: string
  members: string[]
  preferred?: string
  forms: Record<string, VariantForm>
  pairs: Record<string, { n: number; human?: number }>
  ref_policy: string
}

export interface VariantUnknownPair {
  shape: string
  reading: string
  n: number
  human?: number
}

export interface VariantBookMeta {
  edition: string
  built_at?: string
  stats: { groups: number; ref_single: number; ref_multi: number; pairs: number; unknown_pairs: number }
  inputs: { products_records: number; glyph_db_instances: number }
}

export interface VariantBookResponse {
  meta: VariantBookMeta
  groups: Record<string, VariantGroup>
  unknown_pairs: VariantUnknownPair[]
}

export interface GroupTile {
  id: string
  page: number
  patch: string
  char?: string
  reading?: string
  pending: boolean
  stale?: boolean
  audit?: boolean
  human?: string
  channel?: string
  state?: string
}

export interface VariantGroupView {
  canonical: string
  members: string[]
  preferred?: string
  reading_default?: string
  forms: Record<string, VariantForm>
  tiles: GroupTile[]
  n_tiles: number
  n_pending: number
  n_stale: number
  n_audit: number
}

export interface VariantGroupsResponse {
  groups: VariantGroupView[]
}
