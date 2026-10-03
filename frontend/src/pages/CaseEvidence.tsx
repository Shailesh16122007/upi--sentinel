import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, X } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CaseHeader } from '@/components/CaseHeader'
import { EvidenceStatus, needsWork, outcomeLine, SourceProvider, StepList, useSources } from '@/components/evidence'
import { Badge, Button, ErrorNote, Field, inputCls, Panel, PanelHead } from '@/components/ui'
import { api } from '@/lib/api'
import { bytes, cn } from '@/lib/format'
import type { CaseFull, Evidence } from '@/lib/types'

const OPTIONS = [
  { key: 'image', title: 'Screenshots & images', body: 'UPI payment screens, bank SMS, chats, call history.', accept: '.png,.jpg,.jpeg,.webp', formats: 'PNG · JPG · WEBP' },
  { key: 'message', title: 'Messages', body: 'Upload message screenshots or paste the text of an SMS.', accept: '.png,.jpg,.jpeg,.webp,.txt', formats: 'Paste · image · TXT' },
  { key: 'audio', title: 'Audio', body: 'Call recordings or voice notes from the incident.', accept: '.mp3,.wav,.m4a,.aac,.ogg', formats: 'MP3 · WAV · M4A · AAC' },
  { key: 'document', title: 'Documents', body: 'Bank statements, complaint letters, emails saved as PDF.', accept: '.pdf,.docx,.txt', formats: 'PDF · DOCX · TXT' },
] as const

export default function CaseEvidence() {
  const { id = '' } = useParams()
  return <SourceProvider caseId={id}><EvidencePage id={id} /></SourceProvider>
}

function EvidencePage({ id }: { id: string }) {
  const { evidence } = useSources()
  const busy = evidence.some(e => e.status === 'RECEIVED' || e.status === 'PROCESSING')
  const pending = needsWork(evidence)
  const { data: c, error } = useQuery({
    queryKey: ['case', id], queryFn: () => api.case(id),
    refetchInterval: q => (pending || (evidence.length > 0 && !q.state.data?.analyzed_at) ? 1500 : false),
  })
  if (error) return <ErrorNote>{(error as Error).message}</ErrorNote>
  if (!c) return null
  return (
    <>
      <CaseHeader c={c} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Uploader c={c} />
        <div className="space-y-4">
          <EvidenceList caseId={id} evidence={evidence} />
          <Pipeline c={c} evidence={evidence} busy={busy} />
        </div>
      </div>
    </>
  )
}

function Uploader({ c }: { c: CaseFull }) {
  const qc = useQueryClient()
  const pickers = useRef<Record<string, HTMLInputElement | null>>({})
  const [over, setOver] = useState(false)
  const [when, setWhen] = useState('')
  const [paste, setPaste] = useState(false)
  const [text, setText] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['evidence', c.id] }); qc.invalidateQueries({ queryKey: ['case', c.id] }) }
  const up = useMutation({
    mutationFn: ({ files, channel }: { files: File[]; channel?: string }) =>
      api.upload(c.id, files, { channel, occurred_at: when || undefined }),
    onSuccess: refresh,
  })
  const pasteM = useMutation({
    mutationFn: () => api.paste(c.id, { text, label: 'Pasted message', occurred_at: when || null }),
    onSuccess: () => { setText(''); setPaste(false); refresh() },
  })
  const send = (files: FileList | null, channel?: string) => files?.length && up.mutate({ files: Array.from(files), channel })
  const drop = (e: DragEvent) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files) }

  return (
    <Panel onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={drop}
      className={cn('h-fit', over && 'border-accent bg-accent-tint/40')}>
      <div className="px-5 pb-2 pt-4">
        <h2 className="text-[18px] font-semibold">Upload whatever evidence you have</h2>
        <p className="mt-0.5 text-[13px] text-muted">Drop files anywhere in this box, or choose a type. Several files at once is fine.</p>
      </div>
      <div className="grid gap-px border-y border-rule-2 bg-rule-2 sm:grid-cols-2">
        {OPTIONS.map(o => (
          <div key={o.key} className="flex flex-col bg-surface p-4">
            <h3 className="text-[14px] font-semibold">{o.title}</h3>
            <p className="mt-1 flex-1 text-[13px] text-muted">{o.body}</p>
            <p className="mt-2 text-[12px] text-faint">{o.formats}</p>
            <div className="mt-3 flex gap-2">
              <Button size="sm" onClick={() => pickers.current[o.key]?.click()} disabled={up.isPending}>
                {o.key === 'message' ? 'Upload' : 'Choose files'}
              </Button>
              {o.key === 'message' && <Button size="sm" variant={paste ? 'primary' : 'secondary'} onClick={() => setPaste(p => !p)}>Paste text</Button>}
            </div>
            <input hidden multiple type="file" accept={o.accept} ref={el => { pickers.current[o.key] = el }}
              onChange={e => { send(e.target.files, o.key === 'message' ? 'message' : undefined); e.target.value = '' }} />
          </div>
        ))}
      </div>
      {paste && (
        <form className="space-y-2 border-b border-rule-2 p-4" onSubmit={e => { e.preventDefault(); pasteM.mutate() }}>
          <Field label="Paste the message exactly as received">
            <textarea className={inputCls + ' min-h-[110px] font-mono text-[12.5px]'} value={text} onChange={e => setText(e.target.value)} autoFocus
              placeholder={'Your A/C XXXX1234 is debited for Rs.25,000 on 03-10-2026 through UPI. Ref No: 456789123.'} />
          </Field>
          {pasteM.isError && <ErrorNote>{(pasteM.error as Error).message}</ErrorNote>}
          <div className="flex gap-2">
            <Button type="submit" variant="primary" size="sm" disabled={text.trim().length < 3 || pasteM.isPending}>Add message</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setPaste(false)}>Cancel</Button>
          </div>
        </form>
      )}
      <div className="space-y-3 p-4">
        <Field label="When did this happen?" hint="optional — for calls or messages without a visible time">
          <input type="datetime-local" className={inputCls + ' max-w-[260px]'} value={when} onChange={e => setWhen(e.target.value)} />
        </Field>
        <p className="text-[12px] text-faint">Applied to the next upload and shown as an approximate, user-provided time — never as a recorded one.</p>
        {up.isError && <ErrorNote>{(up.error as Error).message}</ErrorNote>}
        {up.data?.[0]?.user_note?.includes('Rejected') && <ErrorNote>{up.data[0].user_note.split('| ')[1]}</ErrorNote>}
        <button className="flex items-center gap-1 text-[13px] text-ink-2 hover:text-ink" onClick={() => setAdvanced(a => !a)}>
          {advanced ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} Advanced evidence
        </button>
        {advanced && (
          <div className="rounded-[var(--radius-sm)] border border-rule-2 bg-paper p-3 text-[13px]">
            <p className="text-muted">Structured exports from a bank or app: transaction history, login / device / authentication logs.
              Column names are matched automatically (date, amount, payee, UTR, device, IP, event…).</p>
            <Button size="sm" className="mt-2" onClick={() => pickers.current.structured?.click()}>Choose CSV or JSON</Button>
            <input hidden multiple type="file" accept=".csv,.json" ref={el => { pickers.current.structured = el }}
              onChange={e => { send(e.target.files); e.target.value = '' }} />
          </div>
        )}
      </div>
    </Panel>
  )
}

function EvidenceList({ caseId, evidence }: { caseId: string; evidence: Evidence[] }) {
  const { open } = useSources()
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <Panel>
      <PanelHead title={`Uploaded evidence (${evidence.length})`} />
      {!evidence.length && <p className="px-4 py-6 text-[13px] text-muted">Nothing uploaded yet. Each file will be listed here with what was actually extracted from it.</p>}
      <ul className="divide-y divide-rule-2">
        {evidence.map(e => {
          const working = e.status === 'RECEIVED' || e.status === 'PROCESSING'
          const isOpen = expanded === e.id || working
          const okish = e.status === 'PROCESSED' || e.status === 'PARTIAL'
          return (
            <li key={e.id} className="px-4 py-2.5">
              <div className="flex items-start gap-2.5">
                <span className="mt-0.5 w-4">
                  {working ? <span className="working mt-1.5 block h-2 w-2 rounded-full bg-accent" />
                    : okish ? <Check className="h-4 w-4 text-ok" /> : <X className="h-4 w-4 text-missing" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <button onClick={() => open({ evidenceId: e.id })} className="font-mono text-[12px] font-medium text-accent-ink hover:underline">{e.code}</button>
                    <span className="truncate text-[13.5px] font-medium">{e.original_name}</span>
                    {e.is_synthetic && <Badge tone="bad">Synthetic</Badge>}
                  </div>
                  <p className="text-[12.5px] text-muted">{outcomeLine(e)} · {bytes(e.size_bytes)}</p>
                </div>
                <EvidenceStatus status={e.status} />
                {!working && <Button variant="ghost" size="sm" aria-label="Toggle processing steps" onClick={() => setExpanded(isOpen ? null : e.id)}>
                  {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </Button>}
              </div>
              {isOpen && <div className="ml-6 mt-2"><StepList steps={e.steps} done={!working} /></div>}
              {e.kind === 'AUDIO' && (e.status === 'UNAVAILABLE' || e.status === 'FAILED') && <TranscriptForm caseId={caseId} ev={e} />}
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

function TranscriptForm({ caseId, ev }: { caseId: string; ev: Evidence }) {
  const qc = useQueryClient()
  const [show, setShow] = useState(false)
  const [text, setText] = useState('')
  const m = useMutation({
    mutationFn: () => api.transcript(caseId, ev.id, text),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['evidence', caseId] }); qc.invalidateQueries({ queryKey: ['case', caseId] }) },
  })
  return (
    <div className="ml-6 mt-2 text-[12.5px]">
      <p className="text-missing">Audio transcription unavailable on this server. The recording is stored unchanged.</p>
      {ev.error && <details className="text-muted"><summary className="cursor-pointer">Technical detail</summary>{ev.error}</details>}
      {!show ? <button className="mt-1 text-accent underline" onClick={() => setShow(true)}>Add a transcript yourself</button> : (
        <div className="mt-2 space-y-2">
          <textarea className={inputCls + ' min-h-[90px] text-[12.5px]'} value={text} onChange={e => setText(e.target.value)}
            placeholder={'[00:00] Hello, I am calling from your bank.\n[00:05] Please approve the UPI request…'} />
          <p className="text-faint">Saved as “transcript provided by user, not machine-generated”.</p>
          {m.isError && <ErrorNote>{(m.error as Error).message}</ErrorNote>}
          <Button size="sm" variant="primary" disabled={text.trim().length < 3 || m.isPending} onClick={() => m.mutate()}>Save transcript</Button>
        </div>
      )}
    </div>
  )
}

function Pipeline({ c, evidence, busy }: { c: CaseFull; evidence: Evidence[]; busy: boolean }) {
  const nav = useNavigate()
  if (!evidence.length) return null
  const n = evidence.length
  const count = (name: string) => evidence.filter(e => e.steps.some(s => s.name === name && s.status !== 'failed')).length
  const extracted = evidence.filter(e => e.steps.some(s => s.name === 'Content extracted' && s.status === 'done')).length
  const ready = !busy && !!c.analyzed_at && evidence.every(e => e.steps.some(s => s.name === 'Evidence linked') || !['PROCESSED', 'PARTIAL'].includes(e.status))
  const rows: [string, number | boolean, string][] = [
    ['File received', count('File received'), `${count('File received')} of ${n}`],
    ['File type detected', count('File type detected'), `${count('File type detected')} of ${n}`],
    ['Content extracted', extracted, `${extracted} of ${n}${extracted < n && !busy ? ` · ${n - extracted} could not be read` : ''}`],
    ['Entities identified', count('Entities identified'), `${count('Entities identified')} of ${n}`],
    ['Transaction information found', !!c.disputed, c.disputed ? `Disputed transaction identified from ${c.disputed.sources.length} source(s)` : busy ? '' : 'No transaction found yet'],
    ['Evidence linked', ready, ready ? `${c.analysis?.counts.anomalies ?? 0} anomalies · ${c.analysis?.counts.conflicts ?? 0} conflicts · ${c.analysis?.counts.missing ?? 0} gaps` : ''],
  ]
  return (
    <Panel>
      <PanelHead title={ready ? 'Investigation ready' : 'Processing evidence'} />
      <ol className="space-y-1.5 px-4 py-3">
        {rows.map(([name, v, detail]) => {
          const ok = typeof v === 'boolean' ? v : v > 0
          return (
            <li key={name} className="flex items-start gap-2 text-[13px]">
              <span className="mt-0.5 w-4">{ok ? <Check className="h-4 w-4 text-ok" /> : <span className={cn('mt-1.5 block h-2 w-2 rounded-full bg-faint', busy && 'working')} />}</span>
              <span className={ok ? 'text-ink' : 'text-muted'}>{name}{detail && <span className="text-muted"> — {detail}</span>}</span>
            </li>
          )
        })}
      </ol>
      <div className="flex items-center justify-between border-t border-rule-2 px-4 py-3">
        <span className="text-[12.5px] text-muted">{busy ? 'Working on your files…' : ready ? 'All submitted evidence has been organised.' : 'Linking evidence…'}</span>
        <Button variant="primary" disabled={!ready} onClick={() => nav(`/cases/${c.id}/investigation`)}>Open investigation</Button>
      </div>
    </Panel>
  )
}
