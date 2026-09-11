import { api } from './client'
import type { ProductResponse } from '../types/products'

export function fetchProduct(book: string, step: string, page: number) {
  const key = `p${String(page).padStart(4, '0')}`
  return api<ProductResponse>(`/api/products/${encodeURIComponent(book)}/${encodeURIComponent(step)}/${key}`)
}

export function overlayUrl(book: string, step: string, page: number, scale = 0.35) {
  return `/api/overlay/${encodeURIComponent(book)}/${encodeURIComponent(step)}/${page}.png?scale=${scale}&t=${Date.now()}`
}
