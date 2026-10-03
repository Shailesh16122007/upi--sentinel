import type {
  Account, AuditRow, Capabilities, CaseActionRow, CaseFull, CaseSummary, Cluster, DemoAccount, EvRequest, Evidence, Finding, Graph,
  NetGraph, Note, Notice, RelatedCase, ReportRow, TimelineEvent, Upload,
} from './types'

const BASE = '/api/v1'
const TOKEN_KEY = 'sentinel.token'

/* Only the sign-in token is kept in the browser. All case data lives in the database. */
export const token = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t) } catch { /* private mode */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ } },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const t = token.get()
  if (t) headers.set('Authorization', `Bearer ${t}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let res: Response
  try {
    res = await fetch(path.startsWith('/api') ? path : BASE + path, { ...init, headers })
  } catch {
    throw new ApiError(0, 'Cannot reach the UPI Sentinel server. Please check your connection and try again.')
  }
  if (!res.ok) {
    let msg = res.status >= 500 ? 'Something went wrong. Please try again.' : `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
      else if (Array.isArray(body.detail)) msg = body.detail.map((d: any) => d.msg).join('; ')
    } catch { /* non-JSON error */ }
    if (res.status === 401 && t) window.dispatchEvent(new Event('sentinel:signed-out'))
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** Authenticated download of evidence/report files; returns an object URL (there are no public file URLs). */
export async function blobUrl(path: string): Promise<string> {
  const t = token.get()
  const res = await fetch(path, { headers: t ? { Authorization: `Bearer ${t}` } : {} })
  if (!res.ok) throw new ApiError(res.status, res.status === 409 ? 'Integrity check failed for this file.' : 'Could not load the file.')
  return URL.createObjectURL(await res.blob())
}

export async function download(path: string, name: string) {
  const u = await blobUrl(path)
  const a = Object.assign(document.createElement('a'), { href: u, download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(u), 2000)
}

const post = <T,>(path: string, body?: unknown) => req<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const qs = (p: Record<string, string | number | boolean | null | undefined>) => {
  const s = new URLSearchParams()
  Object.entries(p).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') s.set(k, String(v)) })
  const x = s.toString()
  return x ? `?${x}` : ''
}

export const api = {
  // auth
  login: (login: string, password: string) => post<{ token: string; account: Account }>('/auth/login', { login, password }),
  logout: () => post<void>('/auth/logout'),
  me: () => req<Account>('/auth/me'),
  updateProfile: (body: Record<string, string | null>) => req<Account>('/auth/me/profile', { method: 'PATCH', body: JSON.stringify(body) }),
  demoAccounts: () => req<DemoAccount[]>('/auth/demo-accounts'),
  banks: () => req<string[]>('/banks'),
  capabilities: () => req<Capabilities>('/system/capabilities'),

  // cases
  cases: (p: Record<string, string | number | boolean | undefined> = {}) => req<CaseSummary[]>(`/cases${qs(p)}`),
  search: (q: string) => req<CaseSummary[]>(`/search${qs({ q })}`),
  dashboard: (synthetic?: boolean) => req<Record<string, number>>(`/dashboard${qs({ synthetic })}`),
  createCase: (body: { statement: string; approx_date?: string | null; claimed_amount?: number | null; synthetic?: boolean }) =>
    post<CaseFull>('/cases', body),
  loadDemo: () => post<{ id: string; ref: string }>('/demo/load'),
  case: (id: string) => req<CaseFull>(`/cases/${id}`),
  victimView: (id: string) => req<{ case: CaseFull; requests: EvRequest[]; updates: { at: string; message: string }[]; banks: string[] }>(`/cases/${id}/victim-view`),
  opened: (id: string) => post<void>(`/cases/${id}/opened`),
  submit: (id: string, bank?: string) => post<CaseFull>(`/cases/${id}/submit`, { bank: bank || null }),
  act: (id: string, action: string, note?: string) => post<CaseFull>(`/cases/${id}/actions`, { action, note: note || null }),
  actions: (id: string) => req<CaseActionRow[]>(`/cases/${id}/actions`),
  dispositions: (id: string, body: Record<string, string | null | undefined>) => post<CaseFull>(`/cases/${id}/dispositions`, body),
  statusOptions: () => req<Record<string, { code: string; label: string; org: string | null }[]>>('/status-options'),
  addStatusOption: (category: string, label: string) => post<{ code: string }>('/status-options', { category, label }),
  selectDisputed: (id: string, transaction_id: string) => post<CaseFull>(`/cases/${id}/disputed-transaction`, { transaction_id }),

  // evidence
  evidence: (id: string) => req<Evidence[]>(`/cases/${id}/evidence`),
  upload: (id: string, files: File[], opts: { channel?: string; occurred_at?: string; note?: string } = {}) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    if (opts.channel) fd.append('channel', opts.channel)
    if (opts.occurred_at) fd.append('occurred_at', opts.occurred_at)
    if (opts.note) fd.append('note', opts.note)
    return req<Upload>(`/cases/${id}/evidence`, { method: 'POST', body: fd })
  },
  paste: (id: string, body: { text: string; label?: string; occurred_at?: string | null }) => post<Upload>(`/cases/${id}/evidence/text`, body),
  transcript: (id: string, evId: string, text: string) => post<Evidence>(`/cases/${id}/evidence/${evId}/transcript`, { text }),
  reprocess: (id: string) => post<{ queued: string[] }>(`/cases/${id}/process`),
  analyze: (id: string) => post<CaseFull>(`/cases/${id}/analyze`),
  fileUrl: (caseId: string, evId: string) => `${BASE}/cases/${caseId}/evidence/${evId}/file`,

  // analysis outputs
  timeline: (id: string) => req<TimelineEvent[]>(`/cases/${id}/timeline`),
  findings: (id: string) => req<Finding[]>(`/cases/${id}/findings`),
  graph: (id: string) => req<Graph>(`/cases/${id}/graph`),
  history: (id: string) => req<{ occurred_at: string | null; amount: number; beneficiary: string | null }[]>(`/cases/${id}/history`),
  related: (id: string) => req<{ related: RelatedCase[]; clusters: Cluster[] }>(`/cases/${id}/related`),
  reviewRelationship: (relId: string, status: string, note?: string) => post<void>(`/relationships/${relId}`, { status, note }),

  // notes, requests
  notes: (id: string) => req<Note[]>(`/cases/${id}/notes`),
  addNote: (id: string, body: { body: string; visibility?: string; finding_code?: string; assessment?: string }) =>
    post<Note>(`/cases/${id}/notes`, body),
  requestItems: () => req<string[]>('/request-items'),
  requests: (id: string) => req<EvRequest[]>(`/cases/${id}/requests`),
  allRequests: (status = 'OPEN') => req<EvRequest[]>(`/requests${qs({ status })}`),
  createRequest: (id: string, items: string[], message: string) => post<EvRequest>(`/cases/${id}/requests`, { items, message }),
  respond: (reqId: string, note?: string) => post<EvRequest>(`/requests/${reqId}/respond`, { note: note || null }),

  // reports & export
  reports: (id: string) => req<ReportRow[]>(`/cases/${id}/reports`),
  allReports: () => req<ReportRow[]>('/reports'),
  makeReport: (id: string, audience?: string) => post<ReportRow>(`/cases/${id}/reports`, audience ? { audience } : {}),
  exportPreview: (id: string) => req<Record<string, any>>(`/cases/${id}/export`),
  exportUrl: (id: string) => `${BASE}/cases/${id}/export/download`,

  // network
  clusters: (synthetic = false) => req<Cluster[]>(`/network/clusters${qs({ synthetic })}`),
  network: (synthetic = false, cluster_id?: string) => req<NetGraph>(`/network/graph${qs({ synthetic, cluster_id })}`),
  relatedOverview: (synthetic = false) => req<(CaseSummary & { related: RelatedCase[] })[]>(`/related-cases${qs({ synthetic })}`),

  // audit, notifications
  audit: (id: string) => req<AuditRow[]>(`/cases/${id}/audit`),
  auditAll: () => req<AuditRow[]>('/audit/cases'),
  notifications: () => req<{ unread: number; items: Notice[] }>('/notifications'),
  markRead: (ids?: string[]) => post<void>('/notifications/read', { ids: ids ?? null }),
}
