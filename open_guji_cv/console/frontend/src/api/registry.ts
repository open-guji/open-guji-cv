import { api } from './client'
import type { Book, Pipeline } from '../types/registry'

export const listBooks = () => api<Book[]>('/api/books')

/** 单册书：`edition`（keben / modern）与 `pipeline`（这册默认走哪条管线）
 * 决定控制台该看哪些后端 step id——现代印刷本的 Step1–3 是另一套 id。 */
export const getBook = (id: string) =>
  listBooks().then((bs) => bs.find((b) => b.id === id))
export const listPipelines = () => api<Pipeline[]>('/api/pipelines')
