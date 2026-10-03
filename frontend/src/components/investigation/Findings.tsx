import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Sources } from '@/components/evidence'
import { Badge, Button, ErrorNote, inputCls, Panel, PanelHead, selectCls } from '@/components/ui'
import { api } from '@/lib/api'
import { cn, dateTime } from '@/lib/format'
import type { Finding } from '@/lib/types'

const CATS: { key: Finding['category']; title: string; sub: string; rule: string }[] = [
  { key: 'SUPPORTING', title: 'Supporting evidence', sub: 'Consistent with the customer’s account of what happened.', rule: 'border-l-support' },
  { key: 'CONTRADICTORY', title: 'Contradictory evidence', sub: 'Conflicts with the customer’s statement. Needs review, not a conclusion.', rule: 'border-l-contra' },
  { key: 'CONTEXTUAL', title: 'Contextual evidence', sub: 'Relevant, but does not favour either side (includes evidence conflicts and patterns).', rule: 'border-l-context' },
  { key: 'MISSING', title: 'Missing evidence', sub: 'Would materially help the investigation but was not provided.', rule: 'border-l-missing' },
]
const ASSESS: Record<string, { label: string; tone: 'ok' | 'bad' | 'warn' }> = {
  AGREE: { label: 'Investigator agrees', tone: 'ok' }, DISAGREE: { label: 'Investigator disagrees', tone: 'bad' },
  NEEDS_REVIEW: { label: 'Needs further review', tone: 'warn' },
}

function Review({ caseId, f }: { caseId: string; f: Finding }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [assessment, setAssessment] = useState('DISAGREE')
  const [body, setBody] = useState('')
  const m = useMutation({
    mutationFn: () => api.addNote(caseId, { body, finding_code: f.code, assessment }),
    onSuccess: () => { setOpen(false); setBody(''); qc.invalidateQueries({ queryKey: ['findings', caseId] }); qc.invalidateQueries({ queryKey: ['notes', caseId] }) },
  })
  return (
    <div className="mt-2">
      {f.human_reviews.map(r => (
        <div key={r.id} className="mb-1.5 rounded-[var(--radius-sm)] border border-rule bg-paper px-3 py-2 text-[12.5px]">
          <div className="flex flex-wrap items-center gap-2"><Badge tone={ASSESS[r.assessment]?.tone}>{ASSESS[r.assessment]?.label ?? r.assessment}</Badge>
            <span className="text-muted">Human note · {r.author} · {dateTime(r.created_at)}</span></div>
          <p className="mt-1 whitespace-pre-wrap">{r.body}</p>
        </div>
      ))}
      {!open ? <button className="text-[12.5px] text-accent hover:underline" onClick={() => setOpen(true)}>Add your assessment</button> : (
        <form className="space-y-2 rounded-[var(--radius-sm)] border border-rule-2 p-2" onSubmit={e => { e.preventDefault(); m.mutate() }}>
          <div className="flex flex-wrap gap-2">
            <select className={selectCls} value={assessment} onChange={e => setAssessment(e.target.value)} aria-label="Assessment">
              <option value="AGREE">Agree</option><option value="DISAGREE">Disagree</option><option value="NEEDS_REVIEW">Needs further review</option>
            </select>
            <span className="self-center text-[12px] text-muted">Kept separate from the system finding; never overwritten by re-analysis.</span>
          </div>
          <textarea className={inputCls + ' min-h-[64px] text-[13px]'} value={body} onChange={e => setBody(e.target.value)}
            placeholder="For example: Beneficiary was actually known to the customer. Internal bank record confirms prior relationship." />
          {m.isError && <ErrorNote>{(m.error as Error).message}</ErrorNote>}
          <div className="flex gap-2"><Button size="sm" variant="primary" disabled={!body.trim() || m.isPending}>Save assessment</Button>
            <Button size="sm" type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button></div>
        </form>
      )}
    </div>
  )
}

export function FindingRow({ f, caseId }: { f: Finding; caseId?: string }) {
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13.5px] font-medium">{f.title}</span>
        {f.is_anomaly && <Badge tone="warn">Anomalous activity</Badge>}
        {f.is_conflict && <Badge tone="bad">Conflict</Badge>}
        {f.certainty && <Badge tone="outline" title={f.certainty_basis ?? undefined}>Certainty: {f.certainty}</Badge>}
        <Sources sources={f.sources} />
      </div>
      {f.detail && <p className="mt-0.5 max-w-[100ch] text-[13px] text-ink-2">
        {f.code === 'SEQUENCE_ANOMALY' && Array.isArray(f.data?.chain) ? 'Events in the 30 minutes before the payment.' : f.detail}
      </p>}
      {f.code === 'SEQUENCE_ANOMALY' && Array.isArray(f.data?.chain) && (
        <ol className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
          {f.data.chain.map((s: string, i: number) => /^\d+ min$/.test(s)
            ? <li key={i} className="text-faint">— {s} →</li>
            : <li key={i} className="rounded-[var(--radius-sm)] border border-rule bg-paper px-1.5 py-0.5">{s}</li>)}
        </ol>
      )}
      {f.category !== 'MISSING' && f.why && (
        <p className="mt-1 max-w-[100ch] text-[12.5px] text-muted"><span className="font-medium text-ink-2">Why it matters:</span> {f.why}
          {f.certainty_basis && <> <span className="font-medium text-ink-2">How certain:</span> {f.certainty} — {f.certainty_basis}</>}</p>
      )}
      {caseId && f.category !== 'MISSING' && <Review caseId={caseId} f={f} />}
    </li>
  )
}

export function FindingsView({ findings, caseId }: { findings: Finding[]; caseId?: string }) {
  return (
    <div className="space-y-5">
      <p className="max-w-[90ch] text-[13px] text-muted">
        System findings are generated only from the submitted evidence. Each says what was found, why it matters, where it came from and how
        certain it is. Anomalous activity is a pattern worth checking, not a fraud determination. Investigator assessments are stored separately.
      </p>
      {CATS.map(cat => {
        const rows = findings.filter(f => f.category === cat.key)
        return (
          <Panel key={cat.key} className={cn('border-l-[3px]', cat.rule)}>
            <PanelHead title={`${cat.title} (${rows.length})`} sub={cat.sub} />
            {rows.length ? <ul className="divide-y divide-rule-2">{rows.map(f => <FindingRow key={f.id} f={f} caseId={caseId} />)}</ul>
              : <p className="px-4 py-3 text-[13px] text-muted">None identified from the submitted evidence.</p>}
          </Panel>
        )
      })}
    </div>
  )
}
