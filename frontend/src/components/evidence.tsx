import { useQuery } from '@tanstack/react-query'
import { Check, Circle, X } from 'lucide-react'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, blobUrl } from '@/lib/api'
import { bytes, cn, dateTime, humanize, kindLabel, methodLabel, mmss } from '@/lib/format'
import type { Entity, Evidence, SourceRef, Step } from '@/lib/types'
import { Badge, Button } from './ui'

/* ------------------------------------------------------------------ source panel context */

type Target = { evidenceId: string; entityId?: string; locator?: string }
type Ctx = { caseId: string; evidence: Evidence[]; open: (t: Target) => void; byId: Map<string, Evidence> }
const SourceCtx = createContext<Ctx | null>(null)

export function useSources() {
  const c = useContext(SourceCtx)
  if (!c) throw new Error('SourceProvider missing')
  return c
}

export function SourceProvider({ caseId, children }: { caseId: string; children: ReactNode }) {
  const { data: evidence = [] } = useQuery({
    queryKey: ['evidence', caseId], queryFn: () => api.evidence(caseId),
    refetchInterval: q => (q.state.data && needsWork(q.state.data) ? 1500 : false),
  })
  const [target, setTarget] = useState<Target | null>(null)
  const byId = useMemo(() => new Map(evidence.map(e => [e.id, e])), [evidence])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setTarget(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const ev = target ? byId.get(target.evidenceId) : undefined
  return (
    <SourceCtx.Provider value={{ caseId, evidence, open: setTarget, byId }}>
      {children}
      {ev && <SourcePanel caseId={caseId} ev={ev} target={target!} onClose={() => setTarget(null)} />}
    </SourceCtx.Provider>
  )
}

/** Still processing, or processed but not yet linked by the case analysis. */
export const needsWork = (evs: Evidence[]) => evs.some(e =>
  e.status === 'RECEIVED' || e.status === 'PROCESSING' ||
  ((e.status === 'PROCESSED' || e.status === 'PARTIAL') && e.kind !== 'SYSTEM' && !e.steps.some(s => s.name === 'Evidence linked')))

/* ------------------------------------------------------------------ exhibit tags */

export function ExhibitTag({ source, className }: { source: SourceRef | { evidence_id: string; label?: string }; className?: string }) {
  const { open, byId } = useSources()
  const ev = source.evidence_id ? byId.get(source.evidence_id) : undefined
  if (!source.evidence_id || !ev) return null
  const s = source as SourceRef
  return (
    <button
      type="button"
      onClick={e => { e.stopPropagation(); open({ evidenceId: ev.id, entityId: s.entity_id, locator: s.locator }) }}
      title={`${ev.code} · ${ev.original_name} — open source`}
      className={cn('inline-flex h-[18px] items-center rounded-[2px] border border-accent/35 bg-accent-tint px-1 font-mono text-[11px] font-medium leading-none text-accent-ink hover:border-accent hover:bg-accent hover:text-white', className)}
    >
      {ev.code}
    </button>
  )
}

export function Sources({ sources, className }: { sources: SourceRef[]; className?: string }) {
  const seen = new Set<string>()
  const list = sources.filter(s => s.evidence_id && !seen.has(s.evidence_id) && seen.add(s.evidence_id))
  if (!list.length) return null
  return <span className={cn('inline-flex flex-wrap gap-1', className)}>{list.map(s => <ExhibitTag key={s.evidence_id} source={s} />)}</span>
}

/* ------------------------------------------------------------------ status */

const STATUS: Record<Evidence['status'], { tone: 'ok' | 'warn' | 'bad' | 'neutral' | 'accent'; label: string }> = {
  RECEIVED: { tone: 'neutral', label: 'Queued' },
  PROCESSING: { tone: 'accent', label: 'Processing' },
  PROCESSED: { tone: 'ok', label: 'Processed' },
  PARTIAL: { tone: 'warn', label: 'Read — check values' },
  UNAVAILABLE: { tone: 'warn', label: 'Needs attention' },
  FAILED: { tone: 'bad', label: 'Could not read' },
}
export const EvidenceStatus = ({ status }: { status: Evidence['status'] }) =>
  <Badge tone={STATUS[status].tone}>{status === 'PROCESSING' && <span className="working h-1.5 w-1.5 rounded-full bg-current" />}{STATUS[status].label}</Badge>

export function outcomeLine(e: Evidence): string {
  if (e.status === 'RECEIVED' || e.status === 'PROCESSING') return 'Processing…'
  if (e.status === 'FAILED' || e.status === 'UNAVAILABLE') return e.error ?? 'Could not be read'
  const parts: string[] = [kindLabel(e)]
  if (e.kind === 'IMAGE') parts.push('OCR complete')
  else if (e.kind === 'AUDIO' || e.kind === 'VIDEO') parts.push(e.method === 'PROVIDED_TRANSCRIPT' ? 'Transcript provided' : e.method === 'VIDEO_OCR' ? 'Text read from video' : 'Transcript complete')
  else if (e.pages) parts.push(`${e.pages} page${e.pages > 1 ? 's' : ''} processed`)
  else if (e.kind === 'STRUCTURED') parts.push(`${e.entities.filter(x => x.type === 'HISTORY_TXN' || x.type === 'ACCOUNT_EVENT').length} records read`)
  else parts.push('Text extracted')
  return parts.join(' · ')
}

export function StepList({ steps, done }: { steps: Step[]; done?: boolean }) {
  const order = ['File received', 'File type detected', 'Content extracted', 'Entities identified', 'Transaction information found', 'Evidence linked']
  return (
    <ol className="space-y-1">
      {order.map(name => {
        const s = steps.find(x => x.name === name)
        return (
          <li key={name} className="flex items-start gap-2 text-[12.5px]">
            <span className="mt-0.5 w-3.5 shrink-0">
              {!s ? <Circle className={cn('h-3 w-3 text-faint', !done && 'working')} />
                : s.status === 'done' ? <Check className="h-3.5 w-3.5 text-ok" />
                  : s.status === 'failed' ? <X className="h-3.5 w-3.5 text-contra" />
                    : <Circle className="h-3 w-3 text-faint" />}
            </span>
            <span className={cn(!s || s.status === 'none' ? 'text-muted' : 'text-ink')}>
              {name}{s?.detail && <span className="text-muted"> — {s.detail}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

/* ------------------------------------------------------------------ the panel */

function useBlob(path: string | null) {
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!path) return
    let u: string | null = null
    blobUrl(path).then(x => { u = x; setUrl(x) }).catch(e => setErr(e.message))
    return () => { if (u) URL.revokeObjectURL(u) }
  }, [path])
  return { url, err }
}

const ENTITY_ORDER = ['AMOUNT', 'DATETIME', 'DATE', 'TIME', 'UTR', 'UPI_REF', 'TXN_ID', 'UPI_ID', 'PAYEE', 'ACCOUNT', 'BANK', 'STATUS',
  'CHANNEL', 'PHONE', 'EMAIL', 'URL', 'CLAIM', 'ACCOUNT_EVENT', 'HISTORY_TXN', 'DEVICE', 'IP', 'LANGUAGE_SIGNAL', 'APP']

function SourcePanel({ caseId, ev, target, onClose }: { caseId: string; ev: Evidence; target: Target; onClose: () => void }) {
  const needsFile = ev.kind === 'IMAGE' || ev.kind === 'AUDIO' || ev.kind === 'VIDEO' || ev.mime === 'application/pdf'
  const { url, err } = useBlob(needsFile ? api.fileUrl(caseId, ev.id) : null)
  const focus = target.entityId ? ev.entities.find(x => x.id === target.entityId) : undefined
  const locator = focus?.locator ?? target.locator
  const ents = [...ev.entities].filter(x => x.type !== 'HISTORY_TXN' && x.type !== 'LANGUAGE_SIGNAL')
    .sort((a, b) => ENTITY_ORDER.indexOf(a.type) - ENTITY_ORDER.indexOf(b.type))
  const hist = ev.entities.filter(x => x.type === 'HISTORY_TXN').length

  return (
    <aside role="complementary" aria-label={`Source ${ev.code}`}
      className="panel-enter fixed inset-y-0 right-0 z-40 flex w-full max-w-[520px] flex-col border-l border-rule bg-surface shadow-[-8px_0_24px_rgba(19,35,63,0.08)]">
      <header className="flex items-start justify-between gap-3 border-b border-rule px-5 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[13px] font-semibold text-accent-ink">{ev.code}</span>
            <span className="truncate text-[14px] font-semibold">{ev.original_name}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
            <span>{kindLabel(ev)}</span><span aria-hidden>/</span><span>{methodLabel(ev.method)}</span>
            <span aria-hidden>/</span><span>{bytes(ev.size_bytes)}</span>
            <EvidenceStatus status={ev.status} />
            {ev.is_synthetic && <Badge tone="bad">Synthetic demonstration data</Badge>}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close source panel"><X className="h-4 w-4" /></Button>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        {focus && (
          <div className="rounded-[var(--radius-sm)] border-l-2 border-accent bg-accent-tint px-3 py-2 text-[12.5px]">
            <div className="font-medium text-ink">{humanize(focus.type)}: {focus.type === 'CLAIM' ? focus.attrs.description : focus.value}</div>
            <div className="text-muted">{focus.locator && `${focus.locator} · `}{methodLabel(focus.method)} · confidence {Math.round(focus.confidence * 100)}%</div>
          </div>
        )}

        {ev.error && <p className="text-[12.5px] text-missing">{ev.error}</p>}
        {ev.user_note && <p className="text-[12.5px] text-muted">{ev.user_note}</p>}

        {ev.kind === 'IMAGE' && (
          <section>
            <h4 className="mb-2 text-[12.5px] font-semibold text-muted">Original image</h4>
            {url ? <img src={url} alt={`Evidence ${ev.code}`} className="max-h-[420px] w-auto rounded-[var(--radius-sm)] border border-rule" />
              : <p className="text-[12.5px] text-muted">{err ?? 'Loading…'}</p>}
          </section>
        )}
        {ev.mime === 'application/pdf' && url && (
          <a href={url} target="_blank" rel="noreferrer" className="text-[13px] text-accent underline">Open original PDF</a>
        )}

        {(ev.kind === 'AUDIO' || ev.kind === 'VIDEO') && (
          <section>
            <h4 className="mb-2 text-[12.5px] font-semibold text-muted">Original recording{ev.duration_s ? ` · ${mmss(ev.duration_s)}` : ''}</h4>
            {url ? (ev.kind === 'VIDEO' ? <video controls src={url} className="max-h-[320px] w-full rounded-[var(--radius-sm)] border border-rule" />
              : <audio controls src={url} className="w-full" />) : <p className="text-[12.5px] text-muted">{err ?? 'Loading…'}</p>}
            <Transcript ev={ev} locator={locator} />
          </section>
        )}
        {ev.language && ev.language.label !== 'Not enough text' && (
          <p className="text-[12.5px]"><span className="text-muted">Detected language:</span> <span className="font-medium">{ev.language.label}</span>
            <span className="text-faint"> · {ev.language.confidence} confidence · {ev.language.basis}</span></p>
        )}

        {ev.text && ev.kind !== 'AUDIO' && (
          <section>
            <h4 className="mb-2 text-[12.5px] font-semibold text-muted">
              {ev.kind === 'IMAGE' ? 'Text read by OCR' : ev.kind === 'STRUCTURED' ? `Records${hist ? ` (${hist} transactions)` : ''}` : 'Extracted text'}
            </h4>
            <TextView text={ev.text} locator={locator} structured={ev.kind === 'STRUCTURED'} />
          </section>
        )}

        <section>
          <h4 className="mb-2 text-[12.5px] font-semibold text-muted">Extracted information ({ents.length})</h4>
          {ents.length ? <EntityTable ents={ents} focusId={focus?.id} /> : <p className="text-[12.5px] text-muted">Nothing was extracted from this item.</p>}
        </section>

        {ev.image_check && (
          <section>
            <h4 className="mb-2 text-[12.5px] font-semibold text-muted">Image checks</h4>
            <p className={cn('text-[13px] font-medium', ev.image_check.indicators.length ? 'text-missing' : 'text-ink')}>{ev.image_check.label}</p>
            {ev.image_check.indicators.map(i => <p key={i.code} className="mt-1 text-[12.5px]"><span className="font-medium">{i.label}.</span> <span className="text-muted">{i.detail}</span></p>)}
            <p className="mt-1 text-[12px] text-faint">Checked: {ev.image_check.checks.join('; ')}. {ev.image_check.note}</p>
          </section>
        )}

        <section>
          <h4 className="mb-2 text-[12.5px] font-semibold text-muted">Evidence integrity</h4>
          <dl className="grid grid-cols-[110px_1fr] gap-y-1 text-[12px]">
            <dt className="text-muted">SHA-256</dt><dd className="break-all font-mono text-[11px]">{ev.sha256}</dd>
            <dt className="text-muted">Uploaded</dt><dd>{dateTime(ev.uploaded_at)}{ev.uploaded_by_role ? ` · by ${humanize(ev.uploaded_by_role === 'VICTIM' ? 'customer' : ev.uploaded_by_role)}` : ''}</dd>
            <dt className="text-muted">Original file</dt><dd>{ev.original_name} · {ev.mime} · {bytes(ev.size_bytes)}</dd>
            <dt className="text-muted">Status</dt>
            <dd className={cn(ev.integrity.result === 'MATCH' ? 'text-ok' : ev.integrity.result === 'NOT_VERIFIED' ? 'text-muted' : 'text-contra')}>
              {ev.integrity.status}{ev.integrity.last_verified_at && <span className="text-muted"> · last verified {dateTime(ev.integrity.last_verified_at)}</span>}
            </dd>
            {ev.user_time_hint && <><dt className="text-muted">Time given</dt><dd>{dateTime(ev.user_time_hint)} (by user)</dd></>}
          </dl>
          <p className="mt-1.5 text-[11.5px] text-faint">{ev.integrity.meaning}</p>
        </section>

        <section>
          <h4 className="mb-2 text-[12.5px] font-semibold text-muted">Processing</h4>
          <StepList steps={ev.steps} done />
        </section>
      </div>
    </aside>
  )
}

function TextView({ text, locator, structured }: { text: string; locator?: string | null; structured?: boolean }) {
  const lines = text.split('\n').slice(0, structured ? 80 : 400)
  const focusLine = locator?.match(/^(?:line|row) (\d+)$/)?.[1]
  const target = focusLine ? Number(focusLine) - (locator!.startsWith('row') ? 0 : 1) : -1
  return (
    <pre className="max-h-[320px] overflow-auto rounded-[var(--radius-sm)] border border-rule bg-paper p-2 text-[12px] leading-[1.55] whitespace-pre-wrap">
      {lines.map((l, i) => (
        <div key={i} ref={i === target ? el => el?.scrollIntoView({ block: 'center' }) : undefined}
          className={cn('flex gap-2', i === target && 'bg-accent-tint')}>
          <span className="w-6 shrink-0 select-none text-right font-mono text-[10.5px] text-faint">{i + 1}</span>
          <span className="min-w-0">{l || ' '}</span>
        </div>
      ))}
    </pre>
  )
}

function Transcript({ ev, locator }: { ev: Evidence; locator?: string | null }) {
  if (!ev.segments?.length) {
    return <p className="mt-3 rounded-[var(--radius-sm)] border border-missing/30 bg-missing-tint px-3 py-2 text-[12.5px] text-missing">
      Audio transcription unavailable.{ev.error ? ` ${ev.error}` : ''}
    </p>
  }
  const primary = ev.segments.filter(s => !s.translation)
  const translated = ev.segments.filter(s => s.translation)
  const provided = ev.method === 'PROVIDED_TRANSCRIPT'
  return (
    <div className="mt-3">
      <p className="mb-1.5 text-[12px] text-muted">
        {provided ? 'Transcript provided by the user — not machine-generated.' : `Machine transcript (${methodLabel(ev.method)}${primary[0]?.lang ? `, speech language: ${primary[0].lang}` : ''}).`}
        {' '}Statements are what someone said — not established facts. Speakers are not separated automatically.
      </p>
      <ul className="max-h-[260px] overflow-auto rounded-[var(--radius-sm)] border border-rule bg-paper p-2 text-[12.5px]">
        {primary.map((s, i) => {
          const hit = locator && mmss(s.start) === locator
          return (
            <li key={i} ref={hit ? el => el?.scrollIntoView({ block: 'center' }) : undefined} className={cn('flex gap-2 py-0.5', hit && 'bg-accent-tint')}>
              <span className="w-10 shrink-0 font-mono text-[11px] text-faint">{mmss(s.start)}</span><span>{s.text}</span>
            </li>
          )
        })}
      </ul>
      {translated.length > 0 && (
        <details className="mt-2 text-[12.5px]"><summary className="cursor-pointer text-muted">English translation (machine, for reference — the original above is the evidence)</summary>
          <ul className="mt-1 space-y-0.5">{translated.map((s, i) => <li key={i}><span className="font-mono text-[11px] text-faint">{mmss(s.start)}</span> {s.text}</li>)}</ul>
        </details>
      )}
    </div>
  )
}

function EntityTable({ ents, focusId }: { ents: Entity[]; focusId?: string }) {
  return (
    <table className="w-full text-[12px]">
      <thead><tr className="border-b border-rule text-left text-muted">
        <th className="py-1 pr-2 font-medium">Type</th><th className="py-1 pr-2 font-medium">Value</th>
        <th className="py-1 pr-2 font-medium">Where</th><th className="py-1 text-right font-medium">Conf.</th>
      </tr></thead>
      <tbody>
        {ents.map(x => (
          <tr key={x.id} className={cn('border-b border-rule-2 align-top', x.id === focusId && 'bg-accent-tint')}>
            <td className="py-1 pr-2 text-muted">{x.type === 'CLAIM' ? 'Statement' : humanize(x.type)}</td>
            <td className="py-1 pr-2">
              {x.type === 'CLAIM' ? <><div>{x.attrs.description}</div><div className="text-muted">“{x.value}”</div></>
                : x.type === 'ACCOUNT_EVENT' ? <>{humanize(x.attrs.event)}{x.attrs.device ? ` · ${x.attrs.device}` : ''}</>
                  : <span className={cn(['UTR', 'UPI_REF', 'TXN_ID', 'UPI_ID', 'ACCOUNT'].includes(x.type) && 'font-mono')}>{x.value}</span>}
              {x.occurred_at && x.type !== 'DATETIME' && <div className="text-muted">{dateTime(x.occurred_at)}</div>}
              {x.attrs.ocr_symbol_misread && <div className="text-missing">OCR read the ₹ sign as “{x.attrs.ocr_symbol_misread}”</div>}
              {x.attrs.needs_review && <div className="text-missing">Needs review: {x.attrs.needs_review}</div>}
              {x.attrs.unlabelled_12_digit && <div className="text-missing">Needs review: unlabelled 12-digit number</div>}
            </td>
            <td className="py-1 pr-2 text-muted">{x.locator ?? '—'}</td>
            <td className="tabular py-1 text-right text-muted">{Math.round(x.confidence * 100)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
