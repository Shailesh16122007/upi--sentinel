import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Badge, Empty, Panel, PanelHead, PageHead, Stat } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { inr, lakh } from '@/lib/format'
import { CaseTable } from './Queue'

export default function StaffDashboard() {
  const me = useMe()
  const nav = useNavigate()
  const base = me.role === 'BANK' ? '/bank' : '/cyber'
  const { data: d } = useQuery({ queryKey: ['dashboard'], queryFn: () => api.dashboard(), refetchInterval: 15_000 })
  const { data: real } = useQuery({ queryKey: ['dashboard', 'real'], queryFn: () => api.dashboard(false), refetchInterval: 15_000 })
  const urgentStatus = me.role === 'BANK' ? 'new,action' : 'ESCALATED'
  const { data: urgent = [] } = useQuery({ queryKey: ['cases', urgentStatus], queryFn: () => api.cases({ status: urgentStatus }), refetchInterval: 15_000 })
  const { data: clusters = [] } = useQuery({ queryKey: ['clusters', 'all'], queryFn: async () => [...await api.clusters(false), ...await api.clusters(true)] })
  if (!d) return null
  const synth = real ? d.total - real.total : 0
  return (
    <div className="space-y-6">
      <PageHead title={me.role === 'BANK' ? 'Fraud investigation overview' : 'Cyber crime case overview'}
        sub={<>{me.org} · figures are counted from case records{synth > 0 && <> · includes {synth} synthetic demo case{synth > 1 ? 's' : ''}</>}</>} />
      {me.role === 'BANK' ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="New cases" value={d.new} onClick={() => nav(`${base}/cases?status=new`)} tone={d.new ? 'warn' : undefined} />
          <Stat label="Under review" value={d.under_review} onClick={() => nav(`${base}/cases?status=review`)} />
          <Stat label="Awaiting action" value={d.awaiting_action} hint={`${d.awaiting_customer} with customer · ${d.info_requested_by_cyber} asked by cyber crime`}
            onClick={() => nav(`${base}/cases?status=action`)} />
          <Stat label="Resolved / closed" value={d.resolved} onClick={() => nav(`${base}/cases?status=done`)} />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Cases received" value={d.received} onClick={() => nav(`${base}/cases`)} />
          <Stat label="Pending acceptance" value={d.pending_review} onClick={() => nav(`${base}/escalated`)} tone={d.pending_review ? 'warn' : undefined} />
          <Stat label="Under investigation" value={d.under_investigation} hint={`${d.pending} pending`} onClick={() => nav(`${base}/cases?status=review`)} />
          <Stat label="Resolved / closed" value={d.resolved} onClick={() => nav(`${base}/closed`)} />
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Open disputed amount" value={lakh(d.open_amount)} hint={`${d.amount_known_cases} case(s) with amount found in evidence`} />
        <Stat label="Cases with possible related cases" value={d.with_related_cases} onClick={() => nav(`${base}/related`)} />
        <Stat label="Related transaction clusters" value={d.clusters} onClick={() => nav(`${base}/network`)} />
      </div>

      {clusters.length > 0 && (
        <Panel className="border-contra/30">
          <PanelHead title="Related case alerts" sub="The same beneficiary or contact appears in several submitted cases. This is a possible link, not a finding of an organised network." />
          <ul className="divide-y divide-rule-2">
            {clusters.slice(0, 5).map(c => (
              <li key={c.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[13.5px]">
                <span className="font-mono font-medium">{c.value}</span>
                <span className="text-muted">{c.type_label}</span>
                <span><span className="font-semibold">{c.case_count}</span> cases</span>
                <span className="tabular">{inr(c.total_amount)} total</span>
                {c.window_hours != null && <span className="text-muted">within {c.window_hours < 1 ? '1' : Math.round(c.window_hours)} h</span>}
                {c.is_synthetic && <Badge tone="bad">DEMO · synthetic</Badge>}
                <button className="ml-auto text-accent hover:underline" onClick={() => nav(`${base}/network?cluster=${c.id}${c.is_synthetic ? '&synthetic=1' : ''}`)}>View network</button>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel>
        <PanelHead title={me.role === 'BANK' ? 'Needs attention' : 'Escalated — awaiting acceptance'} />
        {urgent.length ? <CaseTable cases={urgent} base={base} /> : <Empty>Nothing waiting.</Empty>}
      </Panel>
    </div>
  )
}
