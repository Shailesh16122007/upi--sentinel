import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Circle, X } from 'lucide-react'
import { useRef, useState, type DragEvent, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { needsWork, SourceProvider, useSources } from '@/components/evidence'
import { Badge, Button, ErrorNote, Field, FieldStateBadge, inputCls, Panel, selectCls, StatusBadge, SyntheticBadge } from '@/components/ui'
import { api, download } from '@/lib/api'
import { cn, dateTime, inr, kindLabel, shortDate, timeOnly, when } from '@/lib/format'
import type { CaseFull, EvRequest, Evidence, TimelineEvent, TrackerStep, Upload } from '@/lib/types'

export default function VictimCase() {
  const { id = '' } = useParams()
  return <SourceProvider caseId={id}><CasePage id={id} /></SourceProvider>
}

function Section({ title, sub, children, aside, className }: { title: string; sub?: ReactNode; children: ReactNode; aside?: ReactNode; className?: string }) {
  return (
    <Panel className={className}>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-rule-2 px-4 py-3">
        <div><h2 className="text-[16px] font-semibold">{title}</h2>{sub && <p className="mt-0.5 text-[13px] text-muted">{sub}</p>}</div>
        {aside}
      </div>
      <div className="px-4 py-3">{children}</div>
    </Panel>
  )
}

function CasePage({ id }: { id: string }) {
  const { evidence } = useSources()
  const [params] = useSearchParams()
  const working = needsWork(evidence)
  const q = useQuery({ queryKey: ['victim-view', id], queryFn: () => api.victimView(id), refetchInterval: working ? 2000 : 15_000 })
  const tl = useQuery({ queryKey: ['timeline', id, q.data?.case.analyzed_at], queryFn: () => api.timeline(id), enabled: !!q.data?.case.analyzed_at })
  const [submitted, setSubmitted] = useState(false)
  if (q.error) return <ErrorNote>{(q.error as Error).message}</ErrorNote>
  if (!q.data) return <p className="text-muted">Loading your case…</p>
  const { case: c, requests, updates, banks } = q.data
  const openReq = requests.filter(r => r.status === 'OPEN')
  const draft = c.status === 'DRAFT'
  const amount = c.disputed?.amount ?? c.claimed_amount
  const canUpload = c.status !== 'CLOSED'

  return (
    <div className="space-y-5">
      <Link to="/my/cases" className="text-[13px] text-accent hover:underline">← My cases</Link>
      {c.is_synthetic && <div className="rounded-[var(--radius-sm)] bg-contra px-3 py-1.5 text-[12.5px] font-medium text-white">
        Synthetic demonstration case — not a real dispute.</div>}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[13px] text-muted">CASE #{c.ref}</p>
          <div className="tabular mt-0.5 text-[30px] font-semibold leading-none">{amount != null ? inr(amount) : 'Amount not known yet'}</div>
          <p className="mt-1.5 text-[13px] text-muted">{c.submitted_at ? `Submitted ${shortDate(c.submitted_at)}` : `Started ${shortDate(c.created_at)}`} · Last update {when(c.last_update)}</p>
        </div>
        <div className="flex items-center gap-2"><StatusBadge status={c.status} label={c.status_label} className="text-[13px]" />{c.is_synthetic && <SyntheticBadge />}</div>
      </div>

      {submitted && (
        <div role="status" className="rounded-[var(--radius-md)] border border-ok/30 bg-ok-tint px-4 py-3 text-[14px] text-ok">
          <span className="font-semibold">Your case has been submitted for review.</span> Your case ID is <span className="font-mono">{c.ref}</span>.
        </div>
      )}

      {openReq.map(r => <RequestCard key={r.id} r={r} />)}

      {!draft && <Tracker steps={c.tracker} />}

      {(draft || params.get('step') === 'upload' || openReq.length > 0 || canUpload) && canUpload && (
        <Uploader c={c} first={draft && !evidence.length} />
      )}

      {evidence.length > 0 && <Processing caseId={id} evidence={evidence} analyzing={working} />}

      {c.analysis && c.transactions.length > 1 && (draft || c.status === 'EVIDENCE_REQUESTED') && <ChooseTxn c={c} />}
      {c.analysis && <PaymentFacts c={c} />}
      {tl.data && tl.data.length > 0 && <WhatHappened events={tl.data} />}
      {c.analysis?.victim && <WhatWeFound c={c} />}

      {draft && <SubmitBox c={c} banks={banks} working={working} onDone={() => setSubmitted(true)} />}
      {!draft && <Actions c={c} />}
      <ReportBox c={c} />
      {updates.length > 0 && (
        <Section title="Case updates">
          <ul className="space-y-2 text-[13.5px]">{updates.map((u, i) => (
            <li key={i} className="flex gap-3"><span className="w-[150px] shrink-0 text-muted">{when(u.at)}</span><span>{u.message}</span></li>))}</ul>
        </Section>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ tracker */

function Tracker({ steps }: { steps: TrackerStep[] }) {
  return (
    <Section title="Where your case is now">
      <ol className="space-y-2">
        {steps.map(s => (
          <li key={s.key} className="flex items-start gap-3 text-[14px]">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
              {s.state === 'done' ? <Check className="h-4 w-4 text-ok" /> : s.state === 'current'
                ? <span className="h-3 w-3 rounded-full bg-accent" /> : <Circle className="h-3.5 w-3.5 text-faint" />}
            </span>
            <span className={cn(s.state === 'current' && 'font-semibold', s.state === 'todo' && 'text-muted', s.state === 'skipped' && 'text-faint line-through')}>
              {s.label}{s.state === 'skipped' && ' — not needed'}
              {s.note && <span className="block text-[12.5px] font-normal text-missing">{s.note}</span>}
            </span>
          </li>
        ))}
      </ol>
    </Section>
  )
}

function RequestCard({ r }: { r: EvRequest }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const m = useMutation({ mutationFn: () => api.respond(r.id, note), onSuccess: () => qc.invalidateQueries() })
  return (
    <div className="rounded-[var(--radius-md)] border border-missing/40 bg-missing-tint px-4 py-3">
      <p className="text-[15px] font-semibold text-missing">Action required</p>
      <p className="mt-0.5 text-[14px]">Your bank has requested additional evidence: <span className="font-medium">{r.items.join(', ')}</span></p>
      <p className="mt-1 text-[13.5px] text-ink-2">“{r.message}”</p>
      <p className="mt-2 text-[12.5px] text-muted">Upload it below — it is sent to your bank automatically. If you don’t have it, tell the bank:</p>
      <div className="mt-1.5 flex flex-col gap-2 sm:flex-row">
        <input className={inputCls + ' text-[13px]'} value={note} onChange={e => setNote(e.target.value)} placeholder="For example: I don't have a statement for that day." />
        <Button size="sm" disabled={note.trim().length < 3 || m.isPending} onClick={() => m.mutate()}>Send reply</Button>
      </div>
      {m.isError && <div className="mt-2"><ErrorNote>{(m.error as Error).message}</ErrorNote></div>}
    </div>
  )
}

/* ------------------------------------------------------------------ upload */

const OPTIONS = [
  { key: 'image', title: 'Screenshots', body: 'UPI payment screenshots, SMS, chats, bank messages.', accept: 'image/*,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff' },
  { key: 'message', title: 'Messages', body: 'Paste a message or upload a text file.', accept: '.txt' },
  { key: 'audio', title: 'Audio', body: 'Upload a call recording or voice message.', accept: 'audio/*,.mp3,.wav,.m4a,.aac,.ogg,.opus,.amr' },
  { key: 'document', title: 'Documents', body: 'Upload bank statements, complaint letters or PDFs.', accept: '.pdf,.docx,.txt,.eml' },
] as const

function Uploader({ c, first }: { c: CaseFull; first: boolean }) {
  const qc = useQueryClient()
  const pickers = useRef<Record<string, HTMLInputElement | null>>({})
  const [over, setOver] = useState(false)
  const [paste, setPaste] = useState(false)
  const [text, setText] = useState('')
  const [more, setMore] = useState(false)
  const [whenHint, setWhenHint] = useState('')
  const [last, setLast] = useState<Upload | null>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['evidence', c.id] }); qc.invalidateQueries({ queryKey: ['victim-view', c.id] }) }
  const up = useMutation({
    mutationFn: ({ files, channel }: { files: File[]; channel?: string }) => api.upload(c.id, files, { channel, occurred_at: whenHint || undefined }),
    onSuccess: r => { setLast(r); refresh() },
  })
  const pasteM = useMutation({
    mutationFn: () => api.paste(c.id, { text, label: 'Pasted message', occurred_at: whenHint || null }),
    onSuccess: r => { setLast(r); if (r.accepted.length) { setText(''); setPaste(false) } refresh() },
  })
  const send = (files: FileList | null, channel?: string) => { if (files?.length) up.mutate({ files: Array.from(files), channel }) }
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files) }

  return (
    <Panel onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}
      className={cn(over && 'border-accent bg-accent-tint/40')}>
      <div className="border-b border-rule-2 px-4 py-3">
        <h2 className="text-[16px] font-semibold">{first ? 'Upload your proof' : 'Add more evidence'}</h2>
        <p className="mt-0.5 text-[13px] text-muted">You can upload anything that helps explain what happened. You can also drag files here.</p>
      </div>
      <div className="grid gap-px bg-rule-2 sm:grid-cols-2">
        {OPTIONS.map(o => (
          <div key={o.key} className="flex flex-col bg-surface p-4">
            <h3 className="text-[15px] font-semibold">{o.title}</h3>
            <p className="mt-0.5 flex-1 text-[13px] text-muted">{o.body}</p>
            <div className="mt-3 flex gap-2">
              <Button onClick={() => pickers.current[o.key]?.click()} disabled={up.isPending}>{o.key === 'message' ? 'Upload text file' : 'Choose files'}</Button>
              {o.key === 'message' && <Button variant={paste ? 'primary' : 'secondary'} onClick={() => setPaste(p => !p)}>Paste message</Button>}
            </div>
            <input hidden multiple type="file" accept={o.accept} ref={el => { pickers.current[o.key] = el }}
              onChange={e => { send(e.target.files, o.key === 'message' ? 'message' : undefined); e.target.value = '' }} />
          </div>
        ))}
      </div>
      {paste && (
        <form className="space-y-2 border-t border-rule-2 p-4" onSubmit={e => { e.preventDefault(); pasteM.mutate() }}>
          <Field label="Paste the message exactly as you received it">
            <textarea className={inputCls + ' min-h-[110px] text-[13.5px]'} value={text} onChange={e => setText(e.target.value)} autoFocus
              placeholder="Your account has been debited by Rs 25000 through UPI." />
          </Field>
          {pasteM.isError && <ErrorNote>{(pasteM.error as Error).message}</ErrorNote>}
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={text.trim().length < 3 || pasteM.isPending}>Add message</Button>
            <Button type="button" variant="ghost" onClick={() => setPaste(false)}>Cancel</Button>
          </div>
        </form>
      )}
      <div className="space-y-3 border-t border-rule-2 px-4 py-3">
        {up.isPending && <p className="text-[13px] text-accent-ink">Uploading…</p>}
        {up.isError && <ErrorNote>{(up.error as Error).message}</ErrorNote>}
        {last && last.rejected.length > 0 && (
          <div className="space-y-1">{last.rejected.map((r, i) => (
            <p key={i} className="rounded-[var(--radius-sm)] border border-missing/30 bg-missing-tint px-3 py-1.5 text-[13px] text-missing">
              <span className="font-medium">{r.name}:</span> {r.reason}</p>))}</div>
        )}
        <button className="text-[13px] text-ink-2 underline-offset-2 hover:underline" onClick={() => setMore(m => !m)}>
          {more ? 'Hide more options' : 'More options (screen recordings, e-mails, bank exports, time of a call)'}
        </button>
        {more && (
          <div className="space-y-3 rounded-[var(--radius-sm)] border border-rule-2 bg-paper p-3 text-[13px]">
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => pickers.current.video?.click()}>Screen recording (MP4, MOV, WEBM)</Button>
              <Button size="sm" onClick={() => pickers.current.adv?.click()}>Bank export (CSV, JSON)</Button>
            </div>
            <input hidden multiple type="file" accept="video/*,.mp4,.mov,.webm,.3gp" ref={el => { pickers.current.video = el }}
              onChange={e => { send(e.target.files); e.target.value = '' }} />
            <input hidden multiple type="file" accept=".csv,.json" ref={el => { pickers.current.adv = el }}
              onChange={e => { send(e.target.files); e.target.value = '' }} />
            <Field label="When did the call or message happen?" hint="optional — only if the file itself does not show the time">
              <input type="datetime-local" className={inputCls + ' max-w-[260px]'} value={whenHint} onChange={e => setWhenHint(e.target.value)} />
            </Field>
            <p className="text-[12px] text-faint">Used for the next upload and always shown as “around”, never as an exact recorded time.</p>
          </div>
        )}
      </div>
    </Panel>
  )
}

/* ------------------------------------------------------------------ processing (honest per-file steps) */

const STEP_TEXT = (e: Evidence, name: string, status: string) => {
  if (name === 'File received') return 'File received'
  if (name === 'Content extracted') {
    if (status === 'failed') return e.error ?? 'We could not read this file. The original is kept.'
    return e.kind === 'IMAGE' ? 'Screenshot read' : e.kind === 'AUDIO' ? 'Audio converted to text' : e.kind === 'VIDEO'
      ? 'Recording read' : e.kind === 'STRUCTURED' ? 'Records read' : e.kind === 'MESSAGE' ? 'Message read' : 'Document read'
  }
  if (name === 'Transaction information found') return status === 'done' ? 'Transaction details found' : 'No payment details in this file'
  if (name === 'Evidence linked') return status === 'done' ? 'Related information connected' : 'Not connected to the payment'
  return null
}

function Processing({ caseId, evidence, analyzing }: { caseId: string; evidence: Evidence[]; analyzing: boolean }) {
  const { open } = useSources()
  const ok = evidence.filter(e => e.status === 'PROCESSED' || e.status === 'PARTIAL').length
  const bad = evidence.filter(e => e.status === 'FAILED' || e.status === 'UNAVAILABLE').length
  return (
    <Section title={analyzing ? 'Understanding your evidence' : 'Your evidence'}
      sub={<>{ok} of {evidence.length} file{evidence.length > 1 ? 's' : ''} processed successfully{bad ? <span className="text-missing"> · {bad} file{bad > 1 ? 's' : ''} need{bad > 1 ? '' : 's'} attention</span> : ''}</>}>
      <ul className="divide-y divide-rule-2">
        {evidence.map(e => {
          const busy = e.status === 'RECEIVED' || e.status === 'PROCESSING'
          const steps = e.steps.map(s => ({ s, t: STEP_TEXT(e, s.name, s.status) })).filter(x => x.t)
          return (
            <li key={e.id} className="py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <button className="truncate text-[14px] font-medium text-accent-ink hover:underline" onClick={() => open({ evidenceId: e.id })}>{e.original_name}</button>
                <span className="text-[12.5px] text-muted">{kindLabel(e)}</span>
                {e.language && !['English', 'Not enough text', 'Unknown (Latin script)'].includes(e.language.label) && <Badge tone="outline">Language: {e.language.label}</Badge>}
              </div>
              <ul className="mt-1 space-y-0.5 text-[13px]">
                {steps.map(({ s, t }) => (
                  <li key={s.name} className="flex items-start gap-2">
                    {s.status === 'done' ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" /> : s.status === 'failed'
                      ? <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-missing" /> : <Circle className="mt-1 h-2.5 w-2.5 shrink-0 text-faint" />}
                    <span className={cn(s.status === 'failed' && 'text-missing', s.status === 'none' && 'text-muted')}>{t}</span>
                  </li>
                ))}
                {busy && <li className="flex items-center gap-2 text-muted"><span className="working h-2 w-2 rounded-full bg-accent" />Reading this file…</li>}
              </ul>
              {(e.kind === 'AUDIO' || e.kind === 'VIDEO') && (e.status === 'UNAVAILABLE' || e.status === 'FAILED') && <TranscriptForm caseId={caseId} ev={e} />}
            </li>
          )
        })}
      </ul>
      {analyzing && <p className="mt-2 flex items-center gap-2 text-[13px] text-muted"><span className="working h-2 w-2 rounded-full bg-accent" />Connecting related information…</p>}
    </Section>
  )
}

function TranscriptForm({ caseId, ev }: { caseId: string; ev: Evidence }) {
  const qc = useQueryClient()
  const [show, setShow] = useState(false)
  const [text, setText] = useState('')
  const m = useMutation({ mutationFn: () => api.transcript(caseId, ev.id, text), onSuccess: () => qc.invalidateQueries() })
  return (
    <div className="ml-5 mt-1 text-[13px]">
      {!show ? <button className="text-accent underline" onClick={() => setShow(true)}>Type what was said instead</button> : (
        <div className="space-y-2">
          <textarea className={inputCls + ' min-h-[90px] text-[13px]'} value={text} onChange={e => setText(e.target.value)}
            placeholder={'[00:00] Hello, I am calling from your bank.\n[00:05] Please approve the request…'} />
          <p className="text-faint">Saved as “typed by you”, separate from the recording.</p>
          {m.isError && <ErrorNote>{(m.error as Error).message}</ErrorNote>}
          <Button size="sm" variant="primary" disabled={text.trim().length < 3 || m.isPending} onClick={() => m.mutate()}>Save</Button>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ the payment */

function ChooseTxn({ c }: { c: CaseFull }) {
  const qc = useQueryClient()
  const m = useMutation({ mutationFn: (tid: string) => api.selectDisputed(c.id, tid), onSuccess: () => qc.invalidateQueries() })
  return (
    <Section title="Which payment are you reporting?" sub={`We found ${c.transactions.length} payments in your files. Choose the one you are disputing.`}>
      <ul className="space-y-1.5">
        {c.transactions.map(t => (
          <li key={t.id}>
            <label className={cn('flex cursor-pointer items-center gap-3 rounded-[var(--radius-sm)] border px-3 py-2 text-[14px]',
              t.kind === 'DISPUTED' ? 'border-accent bg-accent-tint' : 'border-rule hover:bg-tint')}>
              <input type="radio" name="txn" checked={t.kind === 'DISPUTED'} disabled={m.isPending} onChange={() => m.mutate(t.id)} />
              <span className="tabular font-semibold">{inr(t.amount)}</span>
              <span className="text-muted">{t.occurred_at ? dateTime(t.occurred_at) : t.time_of_day ? `${t.time_of_day} — date unavailable` : 'Time not found'}</span>
              <span className="truncate text-muted">{t.beneficiary_vpa ?? t.beneficiary ?? ''}{t.reference ? ` · Ref ${t.reference}` : ''}</span>
            </label>
          </li>
        ))}
      </ul>
      {m.isError && <div className="mt-2"><ErrorNote>{(m.error as Error).message}</ErrorNote></div>}
    </Section>
  )
}

const FACTS: [string, string][] = [['amount', 'Amount'], ['time', 'Date & time'], ['reference', 'Transaction reference (UTR)'],
  ['beneficiary_vpa', 'Sent to (UPI ID)'], ['beneficiary_name', 'Recipient name']]

function PaymentFacts({ c }: { c: CaseFull }) {
  const d = c.disputed
  const fs = c.analysis?.field_status ?? {}
  const value = (k: string) => {
    if (!d) return null
    if (k === 'amount') return d.amount != null ? inr(d.amount) : null
    if (k === 'time') return d.occurred_at ? (d.time_precision === 'EXACT' ? dateTime(d.occurred_at) : `Around ${dateTime(d.occurred_at)}`)
      : d.time_of_day ? `${d.time_of_day} — date unavailable` : null
    if (k === 'reference') return d.reference
    if (k === 'beneficiary_vpa') return d.beneficiary_vpa
    return d.beneficiary
  }
  return (
    <Section title="The payment you are reporting" sub={d ? 'Read from your files. Nothing here was typed in by us.' : undefined}>
      {!d ? <p className="text-[14px] text-muted">We could not find a payment in your files yet. A UPI screenshot or bank SMS usually helps.</p> : (
        <dl className="divide-y divide-rule-2">
          {FACTS.map(([k, label]) => (
            <div key={k} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-center">
              <dt className="w-[210px] shrink-0 text-[13px] text-muted">{label}</dt>
              <dd className="flex flex-1 flex-wrap items-center gap-2 text-[14.5px]">
                {value(k) ? <span className={cn('tabular', ['reference', 'beneficiary_vpa'].includes(k) && 'font-mono text-[13.5px]')}>{value(k)}</span>
                  : <span className="text-muted">Not found in your files</span>}
                {fs[k] && fs[k].state !== 'NOT_FOUND' && <FieldStateBadge state={fs[k].state} label={fs[k].label.replace('Extracted from', 'From your')} />}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </Section>
  )
}

/* ------------------------------------------------------------------ what happened / what we found */

function WhatHappened({ events }: { events: TimelineEvent[] }) {
  const { open } = useSources()
  const dated = events.filter(e => e.occurred_at)
  const undated = events.filter(e => !e.occurred_at)
  const byDay = new Map<string, TimelineEvent[]>()
  dated.forEach(e => { const k = shortDate(e.occurred_at); byDay.set(k, [...(byDay.get(k) ?? []), e]) })
  const src = (e: TimelineEvent) => e.sources[0]?.evidence_id
  return (
    <Section title="What happened" sub="Built from your files. “Around” means the exact time is not known.">
      {[...byDay.entries()].map(([day, evs]) => (
        <div key={day} className="mb-3">
          <h3 className="mb-1.5 text-[12.5px] font-semibold uppercase tracking-[0.04em] text-muted">{day}</h3>
          <ol className="relative ml-[86px] border-l border-rule">
            {evs.map(e => (
              <li key={e.id} className="relative pb-3 pl-4">
                <span className={cn('tabular absolute -left-[90px] top-0 w-[78px] text-right text-[13px]', e.approximate ? 'text-missing' : 'text-ink-2')}>
                  {e.time_label.includes('time not stated') ? 'Time not shown' : e.approximate ? `Around ${timeOnly(e.occurred_at)}` : timeOnly(e.occurred_at)}
                </span>
                <span className={cn('absolute -left-[5px] top-[6px] h-[9px] w-[9px] rounded-full', e.event_type === 'TRANSACTION' ? 'bg-contra' : e.reliability === 'STATEMENT' ? 'border-2 border-ink-2 bg-surface' : 'bg-ink-2')} />
                <p className={cn('text-[14px]', e.event_type === 'TRANSACTION' && 'font-semibold')}>{e.simple}</p>
                {e.source_kinds.length > 0 && (
                  <p className="text-[12.5px] text-muted">Source: {src(e)
                    ? <button className="text-accent-ink hover:underline" onClick={() => open({ evidenceId: src(e)! })}>{e.source_kinds.join(', ')}</button>
                    : e.source_kinds.join(', ')}</p>
                )}
              </li>
            ))}
          </ol>
        </div>
      ))}
      {undated.length > 0 && (
        <div>
          <h3 className="mb-1 text-[12.5px] font-semibold uppercase tracking-[0.04em] text-muted">Date not known</h3>
          <ul className="space-y-1.5">{undated.map(e => (
            <li key={e.id} className="text-[14px]"><span className="text-muted">{e.time_label.includes('date unavailable') ? e.time_label : 'Time not shown in your files'} — </span>{e.simple}
              {e.source_kinds.length > 0 && <span className="text-[12.5px] text-muted"> (Source: {e.source_kinds.join(', ')})</span>}</li>))}</ul>
        </div>
      )}
    </Section>
  )
}

function WhatWeFound({ c }: { c: CaseFull }) {
  const v = c.analysis!.victim
  const groups: [string, { text: string }[], string][] = [
    ['Unusual activity', v.unusual, 'border-l-missing'],
    ['Related evidence', v.related, 'border-l-support'],
    ['Things the bank will check', v.check, 'border-l-contra'],
    ['Information still missing', v.missing, 'border-l-context'],
  ]
  const any = groups.some(([, items]) => items.length)
  return (
    <Section title="What we found" sub="We connect related information from your files. This is not a decision on your case.">
      {!any && <p className="text-[14px] text-muted">Nothing to show yet.</p>}
      <div className="space-y-3">
        {groups.filter(([, items]) => items.length).map(([title, items, rule]) => (
          <div key={title} className={cn('border-l-[3px] pl-3', rule)}>
            <h3 className="text-[14px] font-semibold">{title}</h3>
            <ul className="mt-0.5 space-y-0.5 text-[14px] text-ink-2">{items.map((x, i) => <li key={i}>{x.text}</li>)}</ul>
          </div>
        ))}
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ submit, actions, report */

function SubmitBox({ c, banks, working, onDone }: { c: CaseFull; banks: string[]; working: boolean; onDone: () => void }) {
  const qc = useQueryClient()
  const [bank, setBank] = useState(c.bank ?? banks[0] ?? '')
  const [confirm, setConfirm] = useState(false)
  const m = useMutation({ mutationFn: () => api.submit(c.id, bank), onSuccess: () => { onDone(); qc.invalidateQueries(); window.scrollTo({ top: 0 }) } })
  const ready = c.evidence_count > 0 && !working
  return (
    <Section title="Review and submit" sub="When you submit, your bank receives your statement and the files exactly as you uploaded them.">
      <ul className="mb-3 space-y-1 text-[14px]">
        <li className="flex items-center gap-2"><Check className="h-4 w-4 text-ok" />Your statement</li>
        <li className="flex items-center gap-2">{c.evidence_count ? <Check className="h-4 w-4 text-ok" /> : <Circle className="h-3.5 w-3.5 text-faint" />}
          {c.evidence_count ? `${c.evidence_count} file${c.evidence_count > 1 ? 's' : ''} uploaded` : 'Upload at least one file'}</li>
        <li className="flex items-center gap-2">{!working ? <Check className="h-4 w-4 text-ok" /> : <span className="working h-2 w-2 rounded-full bg-accent" />}
          {!working ? 'Files read' : 'Still reading your files…'}</li>
      </ul>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field label="Send to your bank">
          <select className={selectCls + ' h-9 min-w-[220px]'} value={bank} onChange={e => setBank(e.target.value)}>
            {banks.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
        </Field>
        {!confirm ? <Button variant="primary" size="lg" disabled={!ready} onClick={() => setConfirm(true)}>Submit case</Button> : (
          <div className="flex gap-2">
            <Button variant="primary" size="lg" disabled={m.isPending} onClick={() => m.mutate()}>{m.isPending ? 'Submitting…' : `Yes, submit to ${bank}`}</Button>
            <Button size="lg" variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
          </div>
        )}
      </div>
      <p className="mt-2 text-[12px] text-faint">Only banks that use UPI Sentinel are listed. You can still add evidence after submitting.</p>
      {m.isError && <div className="mt-2"><ErrorNote>{(m.error as Error).message}</ErrorNote></div>}
    </Section>
  )
}

function Actions({ c }: { c: CaseFull }) {
  return (
    <Section title="What you can do">
      <ul className="space-y-2.5 text-[14px]">
        <li><span className="font-medium">Add more evidence</span> — use “Add more evidence” above; your bank is told automatically.</li>
        <li>
          <span className="font-medium">File a cyber crime complaint</span> <Badge tone="outline">Prototype action</Badge>
          <p className="text-[13px] text-muted">Report on the official National Cyber Crime Reporting Portal (<a className="text-accent underline" href="https://cybercrime.gov.in" target="_blank" rel="noreferrer">cybercrime.gov.in</a>) or call 1930.
            UPI Sentinel does not file it for you; your report below can help you fill it in. {c.escalated_at ? 'Your bank has also escalated this case to cyber crime.' : ''}</p>
        </li>
        <li><span className="font-medium">Contact your bank</span>
          <p className="text-[13px] text-muted">Use the customer care number printed on your bank card or the bank’s official app. Never call numbers given in SMS or by callers.</p></li>
        {c.reversal_status && <li><span className="font-medium">Payment recovery:</span> {c.reversal_status}</li>}
      </ul>
    </Section>
  )
}

function ReportBox({ c }: { c: CaseFull }) {
  const qc = useQueryClient()
  const { data: reps = [] } = useQuery({ queryKey: ['reports', c.id], queryFn: () => api.reports(c.id) })
  const [err, setErr] = useState<string | null>(null)
  const m = useMutation({ mutationFn: () => api.makeReport(c.id), onSuccess: () => qc.invalidateQueries({ queryKey: ['reports', c.id] }) })
  const latest = reps[0]
  return (
    <Section title="Your report" sub="A PDF of your case: your statement, the payment, your files, what happened and what is missing.">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" disabled={!c.analyzed_at || m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? 'Preparing…' : latest ? 'Generate updated report' : 'Generate my report'}</Button>
        {latest && <Button onClick={() => download(latest.download_url, `${c.ref}_report_v${latest.version}.pdf`).catch(e => setErr(e.message))}>
          Download report (version {latest.version})</Button>}
      </div>
      {latest && !latest.is_current && <p className="mt-2 text-[13px] text-missing">Your case has changed since this report was made. Generate an updated report.</p>}
      {(m.isError || err) && <div className="mt-2"><ErrorNote>{err ?? (m.error as Error).message}</ErrorNote></div>}
      {reps.length > 1 && (
        <details className="mt-2 text-[13px]"><summary className="cursor-pointer text-muted">Earlier versions</summary>
          <ul className="mt-1 space-y-0.5">{reps.slice(1).map(r => (
            <li key={r.id}><button className="text-accent hover:underline" onClick={() => download(r.download_url, `${c.ref}_report_v${r.version}.pdf`)}>
              Version {r.version}</button> <span className="text-muted">· {dateTime(r.created_at)} · {r.evidence_count} files</span></li>))}</ul>
        </details>
      )}
    </Section>
  )
}
