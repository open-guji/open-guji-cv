import { api } from './client'
import type { Book, Pipeline } from '../types/registry'

export const listBooks = () => api<Book[]>('/api/books')
export const listPipelines = () => api<Pipeline[]>('/api/pipelines')
