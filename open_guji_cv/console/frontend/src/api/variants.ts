import { api } from './client'
import type { VariantBookResponse, VariantGroupsResponse } from '../types/variants'

export function fetchVariantBook(edition: string) {
  return api<VariantBookResponse>(`/api/variants/book?edition=${encodeURIComponent(edition)}`)
}

export function fetchVariantGroups(book: string, pages: string) {
  return api<VariantGroupsResponse>(`/api/variants/groups?book=${encodeURIComponent(book)}&pages=${encodeURIComponent(pages)}`)
}
