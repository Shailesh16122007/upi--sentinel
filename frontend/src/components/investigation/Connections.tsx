import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Panel, PanelHead, StatusBadge, SyntheticBadge } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { dateTime, inr, shortDate } from '@/lib/format'
import type { CaseFull } from '@/lib/types'
import { GraphView } from './GraphView'

export function RelatedAlert({ c, onOpen }: { c: CaseFull; onOpen: () => void }) {
  const { data } = useQuery({ queryKey: ['related', c.id, c.analyzed_at], queryFn: () => api.related(c.id) })
  const rel = data?.related ?? []
  if (!rel.length) return null
  const ben = data?.clusters.find(cl => cl.entity_type === 'UPI_ID')
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-contra/35 bg-contra-tint px-4 py-2.5 text-[13.5px]">
      <span className="font-semibold text-contra">Related case alert</span>
      <span>{ben ? <>Beneficiary <span className="font-mono">{ben.value}</span> appears in {ben.case_count - 1} other submitted case{ben.case_count > 2 ? 's' : ''}.</>
        : <>{rel.length} other submitted case{rel.length > 1 ? 's share' : ' shares'} an identifier with this case.</>}</span>
      <Button size="sm" className="ml-auto" onClick={onOpen}>View connections</Button>
    </div>
  )
}

export function Connections({ c }: { c: CaseFull }) {
  const me = useMe()
  const nav = useNavigate()
  const qc = useQueryClient()
  const base = me.role === 'BANK' ? '/bank' : '/cyber'
  const { data } = useQuery({ queryKey: ['related', c.id, c.analyzed_at], queryFn: () => api.related(c.id) })
  const graph = useQuery({ queryKey: ['graph', c.id, c.analyzed_at], queryFn: () => api.graph(c.id) })
  const review = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.reviewRelationship(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['related', c.id] }),
  })
  const rel = data?.related ?? []
  return (
    <div className="space-y-5">
      <Panel>
        <PanelHead title={`Possible related cases (${rel.length})`}
          sub="Other submitted cases that contain the same identifier. Marked “possible” until an officer links or dismisses them." />
        {!rel.length ? <p className="px-4 py-3 text-[13px] text-muted">No other submitted case shares an identifier with this case.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-[13px]">
              <thead><tr className="border-b border-rule text-left text-[12px] text-muted">
                {['Case', 'Customer', 'Amount', 'Date', 'Status', 'Shared identifier', 'Relationship', ''].map(h => <th key={h} className="px-3 py-2 font-medium first:pl-4">{h}</th>)}
              </tr></thead>
              <tbody>
                {rel.map(r => (
                  <tr key={r.id} className="border-b border-rule-2 align-top">
                    <td className="whitespace-nowrap px-3 py-2 pl-4 font-mono">{r.ref} {r.is_synthetic && <SyntheticBadge />}
                      <div className="font-sans text-[12px] text-muted">{r.bank}</div></td>
                    <td className="px-3 py-2">{r.victim}</td>
                    <td className="tabular px-3 py-2">{inr(r.amount)}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-muted">{r.occurred_at ? dateTime(r.occurred_at) : shortDate(r.submitted_at)}</td>
                    <td className="px-3 py-2"><StatusBadge status={r.status} label={r.status_label} /></td>
                    <td className="px-3 py-2">{r.links?.map(l => <div key={l.id}><span className="text-muted">{l.type_label}</span> <span className="font-mono">{l.value}</span></div>)}</td>
                    <td className="px-3 py-2">{r.links?.map(l => (
                      <div key={l.id} className="flex flex-wrap items-center gap-1.5">
                        <Badge tone={l.status === 'LINKED' ? 'bad' : l.status === 'DISMISSED' ? 'outline' : 'warn'}>
                          {l.status === 'POSSIBLE' ? 'Possible related case' : l.status === 'LINKED' ? 'Linked by officer' : 'Dismissed'}</Badge>
                        {me.role === 'CYBER' && l.status !== 'LINKED' && <button className="text-[12px] text-accent hover:underline" onClick={() => review.mutate({ id: l.id, status: 'LINKED' })}>Link</button>}
                        {l.status !== 'DISMISSED' && <button className="text-[12px] text-muted hover:underline" onClick={() => review.mutate({ id: l.id, status: 'DISMISSED' })}>Dismiss</button>}
                        {l.status !== 'POSSIBLE' && <button className="text-[12px] text-muted hover:underline" onClick={() => review.mutate({ id: l.id, status: 'POSSIBLE' })}>Undo</button>}
                      </div>))}</td>
                    <td className="px-3 py-2 text-right">{r.can_open ? <button className="text-accent hover:underline" onClick={() => nav(`${base}/cases/${r.id}`)}>Open</button>
                      : <span className="text-[12px] text-faint" title="Not available to your role">No access</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {(data?.clusters.length ?? 0) > 0 && (
        <Panel>
          <PanelHead title="Related transaction clusters" sub="Totals are computed from the linked case records. A cluster does not by itself establish an organised network." />
          <ul className="divide-y divide-rule-2">
            {data!.clusters.map(cl => (
              <li key={cl.id} className="grid gap-2 px-4 py-3 text-[13px] sm:grid-cols-4">
                <div><div className="text-[12px] text-muted">{cl.type_label}</div><div className="font-mono font-medium">{cl.value}</div></div>
                <div><div className="text-[12px] text-muted">Related cases</div><div className="font-semibold">{cl.case_count}</div></div>
                <div><div className="text-[12px] text-muted">Total disputed amount</div><div className="tabular font-semibold">{inr(cl.total_amount)}</div>
                  {cl.amount_known_cases < cl.case_count && <div className="text-[11.5px] text-missing">{cl.case_count - cl.amount_known_cases} case(s) without a known amount</div>}</div>
                <div><div className="text-[12px] text-muted">Time window</div><div>{cl.window_hours != null ? `${cl.window_hours} hours` : '—'}</div>
                  <button className="text-[12px] text-accent hover:underline" onClick={() => nav(`${base}/network?cluster=${cl.id}${cl.is_synthetic ? '&synthetic=1' : ''}`)}>View network</button></div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <div>
        <h3 className="mb-2 text-[14px] font-semibold">Evidence graph</h3>
        <p className="mb-2 text-[12.5px] text-muted">How the evidence in this case connects: files, the transaction, beneficiary, devices, sessions and contacts.</p>
        {graph.data ? <GraphView graph={graph.data} /> : <p className="text-muted">Building graph…</p>}
      </div>
    </div>
  )
}
