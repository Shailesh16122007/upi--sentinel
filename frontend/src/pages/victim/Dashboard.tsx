import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { Button, Empty, ErrorNote, Panel, StatusBadge, SyntheticBadge } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { cn, greeting, inr, shortDate, when } from '@/lib/format'
import type { CaseSummary } from '@/lib/types'

export function CaseCard({ c }: { c: CaseSummary }) {
  const nav = useNavigate()
  const amount = c.disputed_amount ?? c.claimed_amount
  const action = c.status === 'EVIDENCE_REQUESTED' || c.status === 'DRAFT'
  return (
    <Panel className={cn('flex flex-col gap-3 p-4 sm:flex-row sm:items-center', action && 'border-missing/40')}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12.5px] font-medium text-ink-2">{c.ref}</span>
          <StatusBadge status={c.status} label={c.status_label} />
          {c.is_synthetic && <SyntheticBadge />}
        </div>
        <div className="tabular mt-1 text-[22px] font-semibold leading-tight">{amount != null ? inr(amount) : 'Amount not known yet'}</div>
        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[12.5px]">
          <dt className="text-muted">{c.submitted_at ? 'Submitted' : 'Started'}</dt><dd>{shortDate(c.submitted_at ?? c.created_at)}</dd>
          <dt className="text-muted">Last update</dt><dd>{when(c.last_update)}</dd>
          <dt className="text-muted">Next step</dt><dd className={cn(action && 'font-medium text-missing')}>{c.next_action}</dd>
        </dl>
      </div>
      <Button variant={action ? 'primary' : 'secondary'} onClick={() => nav(`/my/cases/${c.id}`)}>View case</Button>
    </Panel>
  )
}

export default function VictimDashboard() {
  const me = useMe()
  const nav = useNavigate()
  const cases = useQuery({ queryKey: ['cases', 'mine'], queryFn: () => api.cases(), refetchInterval: 15_000 })
  const dash = useQuery({ queryKey: ['dashboard'], queryFn: () => api.dashboard(), refetchInterval: 15_000 })
  const d = dash.data
  const list = cases.data ?? []
  const first = me.name.split(' ')[0]
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[14px] text-muted">{greeting()}, {first}</p>
          <h1 className="text-[24px] font-semibold tracking-[-0.01em]">Your cases</h1>
        </div>
        <Button variant="primary" size="lg" onClick={() => nav('/my/cases/new')}>Report a fraud</Button>
      </div>
      {d && (
        <div className="grid grid-cols-3 gap-3">
          <Link to="/my/cases" className="rounded-[var(--radius-md)] border border-rule bg-surface px-4 py-3 hover:border-accent/50">
            <div className="tabular text-[24px] font-semibold">{d.open}</div><div className="text-[13px] text-muted">Open</div>
          </Link>
          <Link to="/my/cases?filter=action" className={cn('rounded-[var(--radius-md)] border bg-surface px-4 py-3 hover:border-accent/50',
            d.action_required ? 'border-missing/50' : 'border-rule')}>
            <div className={cn('tabular text-[24px] font-semibold', d.action_required && 'text-missing')}>{d.action_required}</div>
            <div className="text-[13px] text-muted">Awaiting your action</div>
          </Link>
          <Link to="/my/cases?filter=resolved" className="rounded-[var(--radius-md)] border border-rule bg-surface px-4 py-3 hover:border-accent/50">
            <div className="tabular text-[24px] font-semibold">{d.resolved}</div><div className="text-[13px] text-muted">Resolved</div>
          </Link>
        </div>
      )}
      {cases.isError && <ErrorNote>{(cases.error as Error).message}</ErrorNote>}
      <div className="space-y-3">
        {list.map(c => <CaseCard key={c.id} c={c} />)}
        {cases.isSuccess && !list.length && (
          <Panel><Empty>You have not reported anything yet. If money left your account because of a call, message or link, choose “Report a fraud”.</Empty></Panel>
        )}
      </div>
      <Panel className="p-4 text-[13px]">
        <h2 className="font-semibold">Lost money just now?</h2>
        <p className="mt-1 text-muted">Call your bank immediately to block further payments, and call the national cyber crime helpline <span className="font-medium text-ink">1930</span>.
          The sooner it is reported, the better the chance of stopping the money.</p>
      </Panel>
    </div>
  )
}
