import { api } from './client'

export interface VersionInfo {
  commit: string | null
  subject: string | null
  deployed_at: string
}

export const getVersion = () => api<VersionInfo>('/api/version')
