// 对应 GET /api/products/{book}/{step}/{key}，字段照
// v1 static/js/panels/products.js 的用法反推。

export interface ProductManifestEntry {
  fingerprint?: string
  status?: string
  elapsed?: number
  ts?: number
  code_rev?: string
  [k: string]: unknown
}

export interface ProductResponse {
  book: string
  step: string
  key: string
  manifest: ProductManifestEntry | null
  products: unknown
}
