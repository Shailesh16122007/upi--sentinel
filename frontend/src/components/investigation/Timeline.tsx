import { Sources } from '@/components/evidence'
import { Badge } from '@/components/ui'
import { cn, humanize } from '@/lib/format'
import type { TimelineEvent } from '@/lib/types'

const REL: Record<TimelineEvent['reliability'], string> = {
  DOCUMENTED: 'Documented in a record',
  STATEMENT: 'A statement someone made',
  SYSTEM: 'Recorded by UPI Sentinel',
}

function Marker({ e }: { e: TimelineEvent }) {
  const base = 'absolute -left-[5.5px] top-[7px] h-[11px] w-[11px] rounded-full'
  if (e.reliability === 'STATEMENT') return <span className={cn(base, 'border-2 border-ink-2 bg-surface')} />
  if (e.approximate) return <span className={cn(base, 'border-2 border-dashed border-ink-2 bg-surface')} />
  if (e.reliability === 'SYSTEM') return <span className={cn(base, 'bg-faint')} />
  return <span className={cn(base, e.event_type === 'TRANSACTION' ? 'bg-contra' : 'bg-ink')} />
}

export function TimelineView({ events }: { events: TimelineEvent[] }) {
  const dated = events.filter(e => e.occurred_at)
  const undated = events.filter(e => !e.occurred_at)
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div>
        <ol className="relative ml-[180px] border-l border-rule">
          {dated.map(e => (
            <li key={e.id} className={cn('relative pb-4 pl-5', e.event_type === 'TRANSACTION' && 'pb-5')}>
              <span className={cn('tabular absolute -left-[180px] top-[3px] w-[166px] text-right text-[12.5px]', e.approximate ? 'text-missing' : 'text-ink-2')}>
                {e.time_label.split(' (')[0]}
              </span>
              <Marker e={e} />
              <div className="flex flex-wrap items-center gap-2">
                <span className={cn('text-[13.5px]', e.event_type === 'TRANSACTION' ? 'font-semibold' : 'font-medium')}>{humanize(e.event_type)}</span>
                <Sources sources={e.sources} />
                {e.reliability === 'STATEMENT' && <Badge tone="outline">Statement</Badge>}
                {e.approximate && <Badge tone="warn">Approximate</Badge>}
              </div>
              <p className="mt-0.5 max-w-[85ch] text-[13px] text-muted">{e.description}</p>
              {e.approximate && e.time_label.includes('(') && <p className="text-[12px] text-missing">{e.time_label.slice(e.time_label.indexOf('(') + 1, -1)}</p>}
            </li>
          ))}
        </ol>
        {undated.length > 0 && (
          <div className="mt-4">
            <h4 className="text-[13px] font-semibold">Time not stated in evidence</h4>
            <p className="text-[12.5px] text-muted">These items could not be placed in order. No time has been assumed for them.</p>
            <ul className="mt-2 divide-y divide-rule-2 border-y border-rule-2">
              {undated.map(e => (
                <li key={e.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
                  <span className="font-medium">{humanize(e.event_type)}</span><Sources sources={e.sources} />
                  <span className="basis-full text-muted">{e.description}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <aside className="h-fit space-y-2 text-[12.5px] text-muted">
        <h4 className="font-semibold text-ink">Reading the timeline</h4>
        {(['DOCUMENTED', 'STATEMENT', 'SYSTEM'] as const).map(r => (
          <div key={r} className="relative pl-5"><Marker e={{ reliability: r, approximate: false, event_type: '' } as TimelineEvent} />{REL[r]}</div>
        ))}
        <div className="relative pl-5"><Marker e={{ reliability: 'DOCUMENTED', approximate: true, event_type: '' } as TimelineEvent} />Approximate time (amber)</div>
        <div className="relative pl-5"><Marker e={{ reliability: 'DOCUMENTED', approximate: false, event_type: 'TRANSACTION' } as TimelineEvent} />Disputed transaction</div>
        <p className="pt-2">Times come only from the evidence itself, or from a time you entered at upload (always marked approximate).</p>
      </aside>
    </div>
  )
}
