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
  kind: 'IMAGE' | 'MESSAGE' | 'AUDIO' | 'VIDEO' | 'DOCUMENT' | 'STRUCTURED' | 'SYSTEM'
  subtype: string | null
  original_name: string
  mime: string | null
  size_bytes: number | null
  sha256: string | null
  source: string
  is_synthetic: boolean
  status: 'RECEIVED' | 'PROCESSING' | 'PROCESSED' | 'PARTIAL' | 'UNAVAILABLE' | 'FAILED'
  uploaded_by_role: string | null
  language: { label: string; confidence: string; basis: string; speech_language?: string } | null
  image_check: { status: string; label: string; checks: string[]; indicators: { code: string; label: string; detail: string }[]; note: string } | null
  integrity: { algorithm: string; digest: string; uploaded_at: string; last_verified_at: string | null; verify_count: number
    result: string; status: string; meaning: string }
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
  time_of_day: string | null
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

export type FieldState = { state: 'CONFIRMED' | 'SINGLE_SOURCE' | 'NEEDS_REVIEW' | 'APPROXIMATE' | 'PARTIAL' | 'CONFLICT' | 'NOT_FOUND'; label: string }
export type SimpleItem = { text: string; sources: SourceRef[] }
export type VictimFindings = { unusual: SimpleItem[]; related: SimpleItem[]; check: SimpleItem[]; missing: SimpleItem[] }
export type KeyFinding = { n: number; text: string; code: string; sources: SourceRef[]; is_conflict: boolean; is_anomaly: boolean; category: string }
export type Modus = { code: string; label: string; strength: string; groups: number; signal_groups: string[]; note: string
  signals: { signal: string; label: string; quote: string; evidence_id: string | null; entity_id: string | null; locator: string | null; origin: string; code: string | null }[] }

export type Analysis = {
  counts: Counts
  completeness: { score: number; earned: number; total: number; items: CompletenessItem[]; method: string }
  ml: Record<string, any>
  summary: { text: string; sources: string[] }[]
  summary_engine: string
  context: Record<string, any>
  modus: Modus[]
  key_findings: KeyFinding[]
  victim: VictimFindings
  field_status: Record<string, FieldState>
  candidates: number
}

export type TrackerStep = { key: string; label: string; state: 'done' | 'current' | 'todo' | 'skipped'; at?: string | null; note?: string }
export type AllowedAction = { action: string; label: string; to: string; note_required: boolean }

export type CaseSummary = {
  id: string; ref: string; status: string; status_label: string; statement: string; approx_date: string | null
  claimed_amount: number | null; is_synthetic: boolean; created_at: string; submitted_at: string | null; escalated_at: string | null
  analyzed_at: string | null; last_update: string; evidence_count: number; processing: number; disputed_amount: number | null
  disputed_time: string | null; open_requests: number; bank: string | null; completeness: number | null
  // customer
  next_action?: string; reversal_status?: string | null
  // investigators
  victim?: { name: string; code: string } | null; claim_type?: string | null; counts?: Counts | null; priority?: string
  related_count?: number; disputed_reference?: string | null; beneficiary?: string | null; bank_outcome?: string | null
  account_action?: string | null; with_cyber?: boolean; modus?: string[]; matched_on?: string[]
}

export type CaseFull = CaseSummary & {
  analysis: Analysis | null
  disputed: CaseTxn | null
  transactions: CaseTxn[]
  tracker: TrackerStep[]
  selection: Record<string, any> | null
  allowed_actions: AllowedAction[]
  can_submit?: boolean
  dispositions?: { bank_outcome: string | null; reversal_status: string | null; account_action: string | null; priority: string }
}

export type SourceRef = { evidence_id?: string; entity_id?: string; label?: string; locator?: string }

export type HumanReview = { id: string; author: string; role: string; assessment: string; body: string; created_at: string }
export type Finding = {
  id: string; category: 'SUPPORTING' | 'CONTRADICTORY' | 'CONTEXTUAL' | 'MISSING'; code: string; title: string
  detail: string | null; is_anomaly: boolean; is_conflict: boolean; sources: SourceRef[]; data: Record<string, any>
  why: string | null; certainty: string | null; certainty_basis: string | null; human_reviews: HumanReview[]
}

export type TimelineEvent = {
  id: string; occurred_at: string | null; approximate: boolean; time_label: string; event_type: string
  description?: string; simple: string; source_kinds: string[]; reliability: 'DOCUMENTED' | 'STATEMENT' | 'SYSTEM'
  entity_ids?: string[]; sources: (SourceRef & { name?: string })[]
}

export type GraphNode = {
  id: string; kind: string; label: string; details: Record<string, any>
  sources: { evidence_id: string; label: string; name: string }[]; events: { time: string; description: string }[]
}
export type Graph = { nodes: GraphNode[]; edges: { source: string; target: string; rel: string; basis?: string | null; confidence?: number | null }[] }

export type Note = { id: string; author: string; role: string; body: string; created_at: string; visibility: string
  finding_code: string | null; finding_title: string | null; assessment: string | null }
export type AuditRow = { at: string; action: string; label: string; actor: string; role: string | null; result: string; source?: string
  evidence?: string | null; case_ref?: string; case_id?: string }
export type ReportRow = { id: string; audience: string; version: number; kind: string; created_at: string; sha256: string
  evidence_count: number; case_status: string; status_label: string; changes: string | null; is_current: boolean; download_url: string
  case_id?: string; case_ref?: string }

export type Account = { id: string; email: string; user_code: string; name: string; role: 'VICTIM' | 'BANK' | 'CYBER'
  role_label: string; permissions: string[]; org: string | null; is_demo: boolean; profile: Record<string, any> | null }
export type DemoAccount = { label: string; email: string; password: string; role: string; name: string; org: string | null }
export type Notice = { id: string; kind: string; title: string; body: string | null; case_id: string | null; case_ref: string | null
  created_at: string; read: boolean }
export type EvRequest = { id: string; case_id: string; items: string[]; message: string; status: string; requested_role: string
  target_role: string; requested_by: string | null; created_at: string; fulfilled_at: string | null; response_note: string | null
  evidence: { id: string; code: string; name: string }[]; case_ref?: string; case_status?: string }
export type CaseActionRow = { at: string; action?: string; label?: string; role?: string; actor?: string; to_label?: string
  note?: string | null; message?: string; detail?: Record<string, any> }
export type RelatedCase = { id: string; ref: string; amount: number | null; amount_source: string; occurred_at: string | null
  submitted_at: string | null; status: string; status_label: string; bank: string | null; is_synthetic: boolean; can_open: boolean
  victim: string; relationship: string | null
  links?: { id: string; entity_type: string; type_label: string; value: string; basis: string; status: string; reviewed_at: string | null }[] }
export type Cluster = { id: string; entity_type: string; type_label: string; value: string; is_synthetic: boolean; case_count: number
  total_amount: number; amount_known_cases: number; first_at: string | null; last_at: string | null; window_hours: number | null
  label: string; cases: RelatedCase[] }
export type NetGraph = { nodes: { id: string; kind: 'CASE' | 'IDENTIFIER'; label: string; [k: string]: any }[]
  edges: { source: string; target: string; amount: number | null; role: string | null }[]; clusters: number }
export type Upload = { accepted: Evidence[]; rejected: { name: string; reason: string; duplicate_of?: string }[] }

export type Capabilities = {
  ocr: { available: boolean; engine: string; languages: string }
  speech_to_text: { engine: string; loaded: boolean; error: string | null; enabled: boolean }
  llm_summary: { configured: boolean; fallback: string }
  ml: { model: string; min_history_rows: number }
  limits: { max_upload_mb: number; max_audio_mb: number; max_files_per_case: number }
}
