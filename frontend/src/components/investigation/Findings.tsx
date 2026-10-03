import { Sources } from '@/components/evidence'
import { Badge, Panel, PanelHead } from '@/components/ui'
import { cn } from '@/lib/format'
import type { Finding } from '@/lib/types'

const CATS: { key: Finding['category']; title: string; sub: string; rule: string }[] = [
  { key: 'SUPPORTING', title: 'Supporting evidence', sub: 'Consistent with the customer’s account of what happened.', rule: 'border-l-support' },
  { key: 'CONTRADICTORY', title: 'Contradictory evidence', sub: 'Conflicts with the customer’s statement. Needs review, not a conclusion.', rule: 'border-l-contra' },
  { key: 'CONTEXTUAL', title: 'Contextual evidence', sub: 'Relevant, but does not favour either side.', rule: 'border-l-context' },
  { key: 'MISSING', title: 'Missing evidence', sub: 'Would materially help the investigation but was not provided.', rule: 'border-l-missing' },
]

export function FindingRow({ f }: { f: Finding }) {
  return (
    <li className="px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13.5px] font-medium">{f.title}</span>
        {f.is_anomaly && <Badge tone="warn">Anomalous activity</Badge>}
        {f.is_conflict && <Badge tone="bad">Conflict</Badge>}
        <Sources sources={f.sources} />
      </div>
      {f.detail && <p className="mt-0.5 max-w-[95ch] text-[13px] text-muted">
        {f.code === 'SEQUENCE_ANOMALY' && Array.isArray(f.data?.chain) ? 'Events in the 30 minutes before the payment. This is anomalous activity, not proof of fraud.' : f.detail}
      </p>}
      {f.code === 'SEQUENCE_ANOMALY' && Array.isArray(f.data?.chain) && (
        <ol className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
          {f.data.chain.map((s: string, i: number) => /^\d+ min$/.test(s)
            ? <li key={i} className="text-faint">— {s} →</li>
            : <li key={i} className="rounded-[var(--radius-sm)] border border-rule bg-paper px-1.5 py-0.5">{s}</li>)}
        </ol>
      )}
    </li>
  )
}

export function FindingsView({ findings }: { findings: Finding[] }) {
  return (
    <div className="space-y-5">
      <p className="max-w-[90ch] text-[13px] text-muted">
        Findings are system-generated from the submitted evidence and placed relative to the customer’s claim. Anomalous activity is a
        pattern worth checking, not a fraud determination. The decision belongs to the authorised investigator.
      </p>
      {CATS.map(cat => {
        const rows = findings.filter(f => f.category === cat.key)
        return (
          <Panel key={cat.key} className={cn('border-l-[3px]', cat.rule)}>
            <PanelHead title={`${cat.title} (${rows.length})`} sub={cat.sub} />
            {rows.length ? <ul className="divide-y divide-rule-2">{rows.map(f => <FindingRow key={f.id} f={f} />)}</ul>
              : <p className="px-4 py-3 text-[13px] text-muted">None identified from the submitted evidence.</p>}
          </Panel>
        )
      })}
    </div>
  )
}
