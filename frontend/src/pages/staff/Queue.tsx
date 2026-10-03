import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Badge, Empty, ErrorNote, inputCls, Panel, PageHead, selectCls, StatusBadge, SyntheticBadge } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { cn, inr, shortDate } from '@/lib/format'
import type { CaseSummary } from '@/lib/types'

export function CaseTable({ cases, base }: { cases: CaseSummary[]; base: string }) {
  const nav = useNavigate()
  const me = useMe()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-[13px]">
        <thead>
          <tr className="border-b border-rule text-left text-[12px] text-muted">
            {['Case ID', 'Customer', ...(me.role === 'CYBER' ? ['Bank'] : []), 'Amount', 'Submitted', 'Evidence', 'Status', 'Priority', 'Related', ''].map(h =>
              <th key={h} className={cn('px-3 py-2 font-medium first:pl-4', ['Amount', 'Evidence', 'Related'].includes(h) && 'text-right')}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {cases.map(c => (
            <tr key={c.id} tabIndex={0} onClick={() => nav(`${base}/cases/${c.id}`)} onKeyDown={e => e.key === 'Enter' && nav(`${base}/cases/${c.id}`)}
              className="cursor-pointer border-b border-rule-2 hover:bg-tint">
              <td className="whitespace-nowrap px-3 py-2 pl-4 font-mono text-[12.5px] font-medium">{c.ref} {c.is_synthetic && <SyntheticBadge />}</td>
              <td className="px-3 py-2">{c.victim ? <>{c.victim.name.replace(' (demo)', '')} <span className="text-muted">#{c.victim.code}</span></> : '—'}</td>
              {me.role === 'CYBER' && <td className="px-3 py-2 text-muted">{c.bank}</td>}
              <td className="tabular px-3 py-2 text-right">{c.disputed_amount != null ? inr(c.disputed_amount) : c.claimed_amount != null
                ? <span className="text-muted" title="Amount given by the customer; not found in evidence">{inr(c.claimed_amount)}*</span> : '—'}</td>
              <td className="whitespace-nowrap px-3 py-2 text-muted">{shortDate(c.submitted_at ?? c.created_at)}</td>
              <td className="tabular px-3 py-2 text-right">{c.evidence_count} item{c.evidence_count === 1 ? '' : 's'}{c.processing > 0 && <span className="text-muted"> · {c.processing} processing</span>}</td>
              <td className="px-3 py-2"><StatusBadge status={c.status} label={c.status_label} />{c.open_requests > 0 && <Badge tone="warn" className="ml-1">Request open</Badge>}</td>
              <td className="px-3 py-2">{c.priority === 'HIGH' ? <Badge tone="bad">High</Badge> : <span className="text-muted">Normal</span>}</td>
              <td className="tabular px-3 py-2 text-right">{c.related_count ? <Badge tone="warn">{c.related_count}</Badge> : <span className="text-faint">0</span>}</td>
              <td className="px-3 py-2 text-right text-accent">Open</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const TABS: Record<string, [string, string][]> = {
  BANK: [['', 'All'], ['new', 'New'], ['review', 'Under review'], ['action', 'Action required'], ['escalated', 'Escalated'], ['done', 'Resolved / closed']],
  CYBER: [['', 'All'], ['ESCALATED', 'Pending acceptance'], ['review', 'Under investigation'], ['pending', 'Pending'], ['resolved', 'Resolved'], ['closed', 'Closed']],
}

export default function Queue({ preset, title }: { preset?: string; title?: string }) {
  const me = useMe()
  const base = me.role === 'BANK' ? '/bank' : '/cyber'
  const [p, setP] = useSearchParams()
  const get = (k: string) => p.get(k) ?? ''
  const set = (k: string, v: string) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); setP(n, { replace: true }) }
  const status = preset ?? get('status')
  const synth = get('synthetic')
  const params = { status: status || undefined, q: get('q') || undefined, amount_min: get('amin') || undefined, amount_max: get('amax') || undefined,
    date_from: get('from') || undefined, date_to: get('to') || undefined, completeness_min: get('comp') || undefined,
    beneficiary: get('ben') || undefined, synthetic: synth === '' ? undefined : synth === '1' }
  const { data = [], isSuccess, error } = useQuery({ queryKey: ['cases', params], queryFn: () => api.cases(params as any), refetchInterval: 15_000 })
  return (
    <div>
      <PageHead title={title ?? 'Cases'} sub={`${data.length} case${data.length === 1 ? '' : 's'}${get('q') ? ` matching “${get('q')}”` : ''}`} />
      {!preset && (
        <div className="mb-3 flex flex-wrap gap-0 border-b border-rule">
          {TABS[me.role].map(([k, l]) => (
            <button key={k} onClick={() => set('status', k)}
              className={cn('-mb-px border-b-2 px-3 py-2 text-[13px]', status === k ? 'border-accent font-medium text-ink' : 'border-transparent text-muted hover:text-ink')}>{l}</button>
          ))}
        </div>
      )}
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        <input className={inputCls + ' col-span-2 h-8 py-1 text-[13px]'} placeholder="Case ID, UTR, UPI ID, phone…" defaultValue={get('q')}
          onKeyDown={e => e.key === 'Enter' && set('q', (e.target as HTMLInputElement).value.trim())} aria-label="Search" />
        <input className={inputCls + ' h-8 py-1 text-[13px]'} placeholder="Beneficiary" defaultValue={get('ben')} onBlur={e => set('ben', e.target.value.trim())} aria-label="Beneficiary" />
        <input className={inputCls + ' h-8 py-1 text-[13px]'} placeholder="Min ₹" inputMode="numeric" defaultValue={get('amin')} onBlur={e => set('amin', e.target.value)} aria-label="Minimum amount" />
        <input className={inputCls + ' h-8 py-1 text-[13px]'} placeholder="Max ₹" inputMode="numeric" defaultValue={get('amax')} onBlur={e => set('amax', e.target.value)} aria-label="Maximum amount" />
        <input className={inputCls + ' h-8 py-1 text-[13px]'} type="date" value={get('from')} onChange={e => set('from', e.target.value)} aria-label="Submitted from" />
        <input className={inputCls + ' h-8 py-1 text-[13px]'} type="date" value={get('to')} onChange={e => set('to', e.target.value)} aria-label="Submitted to" />
        <select className={selectCls} value={get('comp')} onChange={e => set('comp', e.target.value)} aria-label="Evidence completeness">
          <option value="">Any completeness</option><option value="40">≥ 40% complete</option><option value="60">≥ 60% complete</option><option value="80">≥ 80% complete</option>
        </select>
      </div>
      <div className="mb-3 flex gap-1 text-[12.5px]">
        {[['', 'All cases'], ['0', 'Real cases'], ['1', 'Synthetic demo cases']].map(([k, l]) => (
          <button key={k} onClick={() => set('synthetic', k)}
            className={cn('rounded-[var(--radius-sm)] border px-2 py-0.5', synth === k ? 'border-accent bg-accent-tint text-accent-ink' : 'border-rule text-muted')}>{l}</button>))}
      </div>
      {error && <ErrorNote>{(error as Error).message}</ErrorNote>}
      <Panel>{data.length ? <CaseTable cases={data} base={base} /> : isSuccess && <Empty>No cases match.</Empty>}</Panel>
      <p className="mt-2 text-[12px] text-faint">* amount given by the customer — not yet found in the evidence.</p>
    </div>
  )
}
