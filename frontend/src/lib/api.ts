import type {
  AuditRow, Capabilities, CaseFull, CaseSummary, Evidence, Finding, Graph, Note, ReportRow, TimelineEvent,
} from './types'

const KEY = import.meta.env.VITE_API_KEY ?? 'demo-psp-key'
const BASE = '/api/v1'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-API-Key', KEY)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let res: Response
  try {
    res = await fetch(path.startsWith('/api') ? path : BASE + path, { ...init, headers })
  } catch {
    throw new ApiError(0, 'Cannot reach the UPI Sentinel server. Check that the backend is running.')
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
      else if (Array.isArray(body.detail)) msg = body.detail.map((d: any) => d.msg).join('; ')
    } catch { /* non-JSON error */ }
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** Authenticated download of evidence/report files; returns an object URL (no public file URLs exist). */
export async function blobUrl(path: string): Promise<string> {
  const res = await fetch(path, { headers: { 'X-API-Key': KEY } })
  if (!res.ok) throw new ApiError(res.status, res.status === 409 ? 'Integrity check failed for this file.' : 'Could not load file.')
  return URL.createObjectURL(await res.blob())
}

export const api = {
  capabilities: () => req<Capabilities>('/system/capabilities'),
  cases: (synthetic?: boolean) => req<CaseSummary[]>(`/cases${synthetic === undefined ? '' : `?synthetic=${synthetic}`}`),
  createCase: (body: { statement: string; approx_date?: string | null; claimed_amount?: number | null }) =>
    req<CaseFull>('/cases', { method: 'POST', body: JSON.stringify(body) }),
  loadDemo: () => req<{ id: string; ref: string }>('/demo/load', { method: 'POST' }),
  case: (id: string) => req<CaseFull>(`/cases/${id}`),
  setStatus: (id: string, status: string) => req<CaseFull>(`/cases/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  opened: (id: string) => req<void>(`/cases/${id}/opened`, { method: 'POST' }),
  evidence: (id: string) => req<Evidence[]>(`/cases/${id}/evidence`),
  upload: (id: string, files: File[], opts: { channel?: string; occurred_at?: string; note?: string } = {}) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    if (opts.channel) fd.append('channel', opts.channel)
    if (opts.occurred_at) fd.append('occurred_at', opts.occurred_at)
    if (opts.note) fd.append('note', opts.note)
    return req<Evidence[]>(`/cases/${id}/evidence`, { method: 'POST', body: fd })
  },
  paste: (id: string, body: { text: string; label?: string; occurred_at?: string | null }) =>
    req<Evidence>(`/cases/${id}/evidence/text`, { method: 'POST', body: JSON.stringify(body) }),
  transcript: (id: string, evId: string, text: string) =>
    req<Evidence>(`/cases/${id}/evidence/${evId}/transcript`, { method: 'POST', body: JSON.stringify({ text }) }),
  reprocess: (id: string) => req<{ queued: string[] }>(`/cases/${id}/process`, { method: 'POST' }),
  analyze: (id: string) => req<CaseFull>(`/cases/${id}/analyze`, { method: 'POST' }),
  timeline: (id: string) => req<TimelineEvent[]>(`/cases/${id}/timeline`),
  findings: (id: string) => req<Finding[]>(`/cases/${id}/findings`),
  graph: (id: string) => req<Graph>(`/cases/${id}/graph`),
  history: (id: string) => req<{ occurred_at: string | null; amount: number; beneficiary: string | null }[]>(`/cases/${id}/history`),
  notes: (id: string) => req<Note[]>(`/cases/${id}/notes`),
  addNote: (id: string, body: string, author: string) =>
    req<Note>(`/cases/${id}/notes`, { method: 'POST', body: JSON.stringify({ body, author }) }),
  reports: (id: string) => req<ReportRow[]>(`/cases/${id}/reports`),
  makeReport: (id: string) => req<ReportRow>(`/cases/${id}/report`, { method: 'POST' }),
  audit: (id: string) => req<AuditRow[]>(`/cases/${id}/audit`),
  fileUrl: (caseId: string, evId: string) => `${BASE}/cases/${caseId}/evidence/${evId}/file`,
}
