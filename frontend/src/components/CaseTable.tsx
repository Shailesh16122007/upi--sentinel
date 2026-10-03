import { useNavigate } from 'react-router-dom'
import { dateTime, inr } from '@/lib/format'
import type { CaseSummary } from '@/lib/types'
import { Badge } from './ui'

export const CASE_STATUS: Record<string, { label: string; tone: 'neutral' | 'accent' | 'ok' | 'warn' }> = {
  OPEN: { label: 'Awaiting evidence', tone: 'neutral' },
  UNDER_REVIEW: { label: 'Under review', tone: 'accent' },
  REPORT_READY: { label: 'Report ready', tone: 'ok' },
  CLOSED: { label: 'Closed', tone: 'neutral' },
}

export function CaseTable({ cases }: { cases: CaseSummary[] }) {
  const nav = useNavigate()
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-rule text-left text-[12px] text-muted">
            <th className="px-4 py-2 font-medium">Case</th>
            <th className="px-2 py-2 font-medium">Statement</th>
            <th className="px-2 py-2 text-right font-medium">Amount</th>
            <th className="px-2 py-2 text-right font-medium">Evidence</th>
            <th className="px-2 py-2 text-right font-medium">Anomalies</th>
            <th className="px-2 py-2 text-right font-medium">Conflicts</th>
            <th className="px-2 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Filed</th>
          </tr>
        </thead>
        <tbody>
          {cases.map(c => (
            <tr key={c.id} tabIndex={0} onClick={() => nav(`/cases/${c.id}`)} onKeyDown={e => e.key === 'Enter' && nav(`/cases/${c.id}`)}
              className="cursor-pointer border-b border-rule-2 hover:bg-tint">
              <td className="whitespace-nowrap px-4 py-2 font-mono text-[12.5px] font-medium">{c.ref}</td>
              <td className="max-w-[360px] truncate px-2 py-2 text-ink-2">{c.statement}</td>
              <td className="tabular px-2 py-2 text-right">{inr(c.disputed_amount ?? c.claimed_amount)}</td>
              <td className="tabular px-2 py-2 text-right">{c.evidence_count}{c.processing > 0 && <span className="text-muted"> ({c.processing} processing)</span>}</td>
              <td className="tabular px-2 py-2 text-right">{c.counts?.anomalies ?? '—'}</td>
              <td className="tabular px-2 py-2 text-right">{c.counts?.conflicts ?? '—'}</td>
              <td className="px-2 py-2"><Badge tone={CASE_STATUS[c.status]?.tone}>{CASE_STATUS[c.status]?.label ?? c.status}</Badge></td>
              <td className="whitespace-nowrap px-4 py-2 text-muted">{dateTime(c.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
