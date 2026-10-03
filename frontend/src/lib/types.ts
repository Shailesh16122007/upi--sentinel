export type Step = { name: string; status: 'done' | 'failed' | 'none'; at: string; detail: string | null }

export type Entity = {
  id: string
  evidence_id: string
  type: string
  value: string
  normalized: string | null
  confidence: number
  method: string
  locator: string | null
  context: string | null
  occurred_at: string | null
  time_precision: string
  attrs: Record<string, any>
}

export type Evidence = {
  id: string
  code: string
  kind: 'IMAGE' | 'MESSAGE' | 'AUDIO' | 'DOCUMENT' | 'STRUCTURED' | 'SYSTEM'
  subtype: string | null
  original_name: string
  mime: string | null
  size_bytes: number | null
  sha256: string | null
  source: string
  is_synthetic: boolean
  status: 'RECEIVED' | 'PROCESSING' | 'PROCESSED' | 'PARTIAL' | 'UNAVAILABLE' | 'FAILED'
  method: string | null
  text: string | null
  pages: number | null
  duration_s: number | null
  segments: { start: number | null; end: number | null; text: string; lang?: string; translation?: boolean; provided?: boolean }[] | null
  quality: number | null
  steps: Step[]
  error: string | null
  user_time_hint: string | null
  user_note: string | null
  uploaded_at: string
  processed_at: string | null
  entities: Entity[]
}

export type FieldValue = { value: string | number; evidence_id: string; entity_id: string; precision?: string }

export type CaseTxn = {
  id: string
  kind: 'DISPUTED' | 'RELATED' | 'HISTORICAL'
  amount: number | null
  occurred_at: string | null
  time_precision: string
  reference: string | null
  beneficiary: string | null
  beneficiary_vpa: string | null
  status: string | null
  channel: string | null
  device: string | null
  fields: Record<string, FieldValue[]>
  sources: string[]
  match_basis: string | null
  match_confidence: number | null
}

export type Counts = {
  anomalies: number; conflicts: number; missing: number; supporting: number; contradictory: number
  contextual: number; evidence: number; history_rows: number
}

export type CompletenessItem = {
  key: string; label: string; weight: number; earned: number; status: 'present' | 'partial' | 'missing'
  basis: string | null; why: string
}

export type Analysis = {
  counts: Counts
  completeness: { score: number; earned: number; total: number; items: CompletenessItem[]; method: string }
  ml: Record<string, any>
  summary: { text: string; sources: string[] }[]
  summary_engine: string
  context: Record<string, any>
}

export type CaseSummary = {
  id: string; ref: string; status: string; statement: string; approx_date: string | null; claimed_amount: number | null
  claim_type: string | null; is_synthetic: boolean; created_at: string; analyzed_at: string | null; evidence_count: number
  processing: number; disputed_amount: number | null; counts: Counts | null; completeness: number | null
}

export type CaseFull = CaseSummary & {
  analysis: Analysis | null
  disputed: CaseTxn | null
  transactions: CaseTxn[]
  linked_risk_txn_id: string | null
}

export type SourceRef = { evidence_id?: string; entity_id?: string; label?: string; locator?: string }

export type Finding = {
  id: string; category: 'SUPPORTING' | 'CONTRADICTORY' | 'CONTEXTUAL' | 'MISSING'; code: string; title: string
  detail: string | null; is_anomaly: boolean; is_conflict: boolean; sources: SourceRef[]; data: Record<string, any>
}

export type TimelineEvent = {
  id: string; occurred_at: string | null; approximate: boolean; time_label: string; event_type: string
  description: string; reliability: 'DOCUMENTED' | 'STATEMENT' | 'SYSTEM'; entity_ids: string[]; sources: SourceRef[]
}

export type GraphNode = {
  id: string; kind: string; label: string; details: Record<string, any>
  sources: { evidence_id: string; label: string; name: string }[]; events: { time: string; description: string }[]
}
export type Graph = { nodes: GraphNode[]; edges: { source: string; target: string; rel: string; basis?: string | null; confidence?: number | null }[] }

export type Note = { id: string; author: string; body: string; created_at: string }
export type AuditRow = { at: string; action: string; actor: string; result: string; source: string; evidence: string | null }
export type ReportRow = { id: string; created_at: string; sha256: string; download_url: string }

export type Capabilities = {
  ocr: { available: boolean; engine: string }
  speech_to_text: { engine: string; loaded: boolean; error: string | null; enabled: boolean }
  llm_summary: { configured: boolean; fallback: string }
  ml: { model: string; min_history_rows: number }
  limits: { max_upload_mb: number; max_audio_mb: number; max_files_per_case: number }
}
