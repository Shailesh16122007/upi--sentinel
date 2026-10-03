import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { SourceProvider } from '@/components/evidence'
import { CaseActions } from '@/components/investigation/CaseActions'
import { Connections, RelatedAlert } from '@/components/investigation/Connections'
import { FindingsView } from '@/components/investigation/Findings'
import { Overview } from '@/components/investigation/Overview'
import { AuditView, SourcesView } from '@/components/investigation/Records'
import { ReportTab } from '@/components/investigation/ReportTab'
import { TimelineView } from '@/components/investigation/Timeline'
import { Badge, ErrorNote, Panel, StatusBadge, SyntheticBadge, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { dateTime, inr } from '@/lib/format'

export default function Workspace() {
  const { id = '' } = useParams()
  return <SourceProvider caseId={id}><Inner id={id} /></SourceProvider>
}

function Inner({ id }: { id: string }) {
  const me = useMe()
  const base = me.role === 'BANK' ? '/bank' : '/cyber'
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'overview'
  const goTo = (t: string) => setParams({ tab: t }, { replace: true })
  const { data: c, error, refetch } = useQuery({ queryKey: ['case', id], queryFn: () => api.case(id), refetchInterval: q => (q.state.data?.processing ? 2000 : 10_000) })
  const key = c?.analyzed_at ?? 'none'
  const findings = useQuery({ queryKey: ['findings', id, key], queryFn: () => api.findings(id), enabled: !!c?.analyzed_at })
  const timeline = useQuery({ queryKey: ['timeline', id, key], queryFn: () => api.timeline(id), enabled: !!c?.analyzed_at })

  const logged = useRef(false)
  useEffect(() => {
    if (!logged.current && id) { logged.current = true; api.opened(id).then(() => refetch()).catch(() => {}) }
  }, [id, refetch])

  if (error) return <ErrorNote>{(error as Error).message}</ErrorNote>
  if (!c) return <p className="text-muted">Loading case…</p>
  const amount = c.disputed?.amount ?? c.claimed_amount
  const f = findings.data ?? []
  return (
    <div className="space-y-4">
      <Link to={`${base}/cases`} className="text-[13px] text-accent hover:underline">← Cases</Link>
      {c.is_synthetic && <div className="rounded-[var(--radius-sm)] bg-contra px-3 py-1.5 text-[12.5px] font-medium text-white">
        Synthetic demonstration data — this case and its evidence are generated for demonstration. Not a real dispute.</div>}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-mono text-[13px] text-muted">CASE #{c.ref}</p>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-3">
            <span className="tabular text-[30px] font-semibold leading-none tracking-[-0.02em]">{inr(amount)}</span>
            <span className="text-[14px] text-muted">{c.disputed?.amount != null ? 'Disputed transaction' : amount ? 'Amount reported by customer — not found in evidence' : 'Amount not established'}</span>
          </div>
          <p className="mt-1.5 text-[12.5px] text-muted">
            {c.victim ? `${c.victim.name} · #${c.victim.code}` : 'Customer not recorded'} · {c.bank}
            {c.submitted_at && ` · submitted ${dateTime(c.submitted_at)}`}{c.escalated_at && ` · escalated ${dateTime(c.escalated_at)}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12.5px] uppercase tracking-[0.04em] text-muted">Status</span>
          <StatusBadge status={c.status} label={c.status_label} className="text-[13px]" />
          {c.priority === 'HIGH' && <Badge tone="bad">High priority</Badge>}
          {c.account_action && <Badge tone="outline">{c.account_action}</Badge>}
          {c.is_synthetic && <SyntheticBadge />}
        </div>
      </div>
      <RelatedAlert c={c} onOpen={() => goTo('connections')} />
      {!c.analyzed_at ? (
        <Panel className="p-6 text-[14px]">{c.processing ? 'Evidence is still being processed. This view opens automatically when it is ready.' : 'No evidence has been analysed for this case yet.'}</Panel>
      ) : (
        <Tabs value={tab} onValueChange={goTo}>
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="timeline">Timeline</TabsTrigger>
            <TabsTrigger value="evidence">Evidence <span className="text-faint">{c.evidence_count}</span></TabsTrigger>
            <TabsTrigger value="connections">Connections {!!c.related_count && <Badge tone="warn">{c.related_count}</Badge>}</TabsTrigger>
            <TabsTrigger value="findings">Findings <span className="text-faint">{f.length}</span></TabsTrigger>
            <TabsTrigger value="report">Investigation report</TabsTrigger>
            <TabsTrigger value="actions">Case actions {c.open_requests > 0 && <Badge tone="warn">{c.open_requests}</Badge>}</TabsTrigger>
            <TabsTrigger value="audit">Audit trail</TabsTrigger>
          </TabsList>
          <div className="pt-5">
            <TabsContent value="overview"><Overview c={c} findings={f} goTo={goTo} /></TabsContent>
            <TabsContent value="timeline">{timeline.data && <TimelineView events={timeline.data} />}</TabsContent>
            <TabsContent value="evidence"><SourcesView /></TabsContent>
            <TabsContent value="connections"><Connections c={c} /></TabsContent>
            <TabsContent value="findings"><FindingsView findings={f} caseId={id} /></TabsContent>
            <TabsContent value="report"><ReportTab c={c} /></TabsContent>
            <TabsContent value="actions"><CaseActions c={c} /></TabsContent>
            <TabsContent value="audit"><AuditView caseId={id} /></TabsContent>
          </div>
        </Tabs>
      )}
    </div>
  )
}
