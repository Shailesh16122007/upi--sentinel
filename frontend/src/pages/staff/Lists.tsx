import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Empty, ErrorNote, Panel, PageHead, StatusBadge, SyntheticBadge } from '@/components/ui'
import { api, download } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { cn, dateTime, humanize, inr, when } from '@/lib/format'

const useBase = () => (useMe().role === 'BANK' ? '/bank' : '/cyber')

export function RelatedCases() {
  const nav = useNavigate()
  const base = useBase()
  const [synthetic, setSynthetic] = useState(false)
  const { data = [], isSuccess } = useQuery({ queryKey: ['related-overview', synthetic], queryFn: () => api.relatedOverview(synthetic) })
  return (
    <div>
      <PageHead title="Related cases" sub="Cases that share a beneficiary, contact number, link or transaction reference with another submitted case."
        aside={<label className="flex items-center gap-1.5 text-[12.5px] text-muted"><input type="checkbox" checked={synthetic} onChange={e => setSynthetic(e.target.checked)} />Synthetic demo data</label>} />
      <div className="space-y-3">
        {isSuccess && !data.length && <Panel><Empty>No possible related cases.</Empty></Panel>}
        {data.map(c => (
          <Panel key={c.id}>
            <button className="flex w-full flex-wrap items-center gap-3 border-b border-rule-2 px-4 py-2.5 text-left hover:bg-tint" onClick={() => nav(`${base}/cases/${c.id}?tab=connections`)}>
              <span className="font-mono font-medium">{c.ref}</span>{c.is_synthetic && <SyntheticBadge />}
              <span className="tabular">{inr(c.disputed_amount ?? c.claimed_amount)}</span>
              <StatusBadge status={c.status} label={c.status_label} />
              <span className="ml-auto text-[13px] text-contra">{c.related.length} possible related case{c.related.length > 1 ? 's' : ''}</span>
            </button>
            <ul className="divide-y divide-rule-2 text-[13px]">
              {c.related.map(r => (
                <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-1.5">
                  <span className="font-mono">{r.ref}</span><span className="tabular">{inr(r.amount)}</span><span className="text-muted">{r.bank}</span>
                  <span className="text-muted">{r.links?.map(l => `${l.type_label} ${l.value}`).join('; ')}</span>
                  <Badge tone={r.links?.some(l => l.status === 'LINKED') ? 'bad' : 'warn'}>{r.links?.some(l => l.status === 'LINKED') ? 'Linked by officer' : 'Possible related case'}</Badge>
                </li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>
    </div>
  )
}

export function Reports() {
  const base = useBase()
  const nav = useNavigate()
  const [err, setErr] = useState<string | null>(null)
  const { data = [], isSuccess } = useQuery({ queryKey: ['all-reports'], queryFn: api.allReports })
  return (
    <div>
      <PageHead title="Reports" sub="Latest version of every report generated for cases you can see. Open a case to generate a new version." />
      {err && <ErrorNote>{err}</ErrorNote>}
      <Panel>
        {isSuccess && !data.length && <Empty>No reports generated yet.</Empty>}
        {data.length > 0 && (
          <table className="w-full text-[13px]">
            <thead><tr className="border-b border-rule text-left text-[12px] text-muted">{['Case', 'Report', 'Version', 'Generated', 'Case status', ''].map(h => <th key={h} className="px-3 py-2 font-medium first:pl-4">{h}</th>)}</tr></thead>
            <tbody>{data.map(r => (
              <tr key={r.id} className="border-b border-rule-2">
                <td className="px-3 py-2 pl-4"><button className="font-mono text-accent hover:underline" onClick={() => nav(`${base}/cases/${r.case_id}?tab=report`)}>{r.case_ref}</button></td>
                <td className="px-3 py-2">{r.audience === 'BANK' ? 'Bank investigation' : 'Cyber crime investigation'}</td>
                <td className="px-3 py-2">v{r.version}</td>
                <td className="px-3 py-2 text-muted">{dateTime(r.created_at)}</td>
                <td className="px-3 py-2 text-muted">{r.case_status}</td>
                <td className="px-3 py-2 text-right"><button className="text-accent hover:underline"
                  onClick={() => download(r.download_url, `${r.case_ref}_${r.audience.toLowerCase()}_v${r.version}.pdf`).catch(e => setErr(e.message))}>Download</button></td>
              </tr>))}</tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}

export function AuditAll() {
  const base = useBase()
  const nav = useNavigate()
  const { data = [] } = useQuery({ queryKey: ['audit-all'], queryFn: api.auditAll, refetchInterval: 15_000 })
  return (
    <div>
      <PageHead title="Audit" sub="Most recent 200 events across cases you can see. Append-only; nothing here can be edited." />
      <Panel>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[13px]"><tbody>
            {data.map((a, i) => (
              <tr key={i} className="border-b border-rule-2">
                <td className="whitespace-nowrap px-4 py-1.5 text-muted">{dateTime(a.at)}</td>
                <td className="px-2 py-1.5"><button className="font-mono text-[12.5px] text-accent hover:underline" onClick={() => nav(`${base}/cases/${a.case_id}?tab=audit`)}>{a.case_ref}</button></td>
                <td className="px-2 py-1.5">{a.label}</td>
                <td className="px-2 py-1.5 text-muted">{a.result !== 'OK' ? a.result : ''}</td>
                <td className="whitespace-nowrap px-4 py-1.5 text-right text-[12px] text-faint">{a.actor}{a.role ? ` · ${a.role === 'VICTIM' ? 'Customer' : humanize(a.role)}` : ''}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      </Panel>
    </div>
  )
}

export function Requests() {
  const base = useBase()
  const nav = useNavigate()
  const [status, setStatus] = useState('OPEN')
  const { data = [], isSuccess } = useQuery({ queryKey: ['all-requests', status], queryFn: () => api.allRequests(status), refetchInterval: 15_000 })
  return (
    <div>
      <PageHead title="Evidence requests" sub="Requests to customers, and information requests from cyber crime to your bank." />
      <div className="mb-3 flex gap-1 text-[13px]">
        {[['OPEN', 'Open'], ['FULFILLED', 'Answered']].map(([k, l]) => (
          <button key={k} onClick={() => setStatus(k)} className={cn('rounded-[var(--radius-sm)] border px-3 py-1', status === k ? 'border-accent bg-accent-tint text-accent-ink' : 'border-rule text-ink-2')}>{l}</button>))}
      </div>
      <Panel>
        {isSuccess && !data.length && <Empty>No {status === 'OPEN' ? 'open' : 'answered'} requests.</Empty>}
        <ul className="divide-y divide-rule-2">
          {data.map(r => (
            <li key={r.id}>
              <button className="block w-full px-4 py-2.5 text-left text-[13px] hover:bg-tint" onClick={() => nav(`${base}/cases/${r.case_id}?tab=actions`)}>
                <div className="flex flex-wrap items-center gap-2"><span className="font-mono font-medium">{r.case_ref}</span>
                  <Badge tone={r.target_role === 'VICTIM' ? 'accent' : 'warn'}>{r.target_role === 'VICTIM' ? 'Waiting for customer' : 'Asked of bank by cyber crime'}</Badge>
                  <span className="text-muted">{r.case_status}</span><span className="ml-auto text-faint">{when(r.created_at)}</span></div>
                <p className="mt-0.5">{r.items.join(', ')} — <span className="text-muted">“{r.message}”</span></p>
                {r.fulfilled_at && <p className="text-muted">Answered {dateTime(r.fulfilled_at)}{r.evidence.length ? ` with ${r.evidence.map(e => e.code).join(', ')}` : ''}</p>}
              </button>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
