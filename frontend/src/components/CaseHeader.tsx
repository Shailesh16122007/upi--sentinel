import { useMutation, useQueryClient } from '@tanstack/react-query'
import { NavLink } from 'react-router-dom'
import { api } from '@/lib/api'
import { cn, dateTime, inr } from '@/lib/format'
import type { CaseFull } from '@/lib/types'
import { CASE_STATUS } from './CaseTable'
import { Badge } from './ui'

export function CaseHeader({ c }: { c: CaseFull }) {
  const qc = useQueryClient()
  const status = useMutation({
    mutationFn: (s: string) => api.setStatus(c.id, s),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['case', c.id] }),
  })
  const amount = c.disputed?.amount ?? c.claimed_amount
  return (
    <div className="mb-5">
      {c.is_synthetic && (
        <div className="mb-3 rounded-[var(--radius-sm)] bg-contra px-3 py-1.5 text-[12.5px] font-medium text-white">
          Synthetic demonstration data — this case and all its evidence are generated for demonstration. It is not a real dispute.
        </div>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-mono text-[12.5px] text-muted">Case #{c.ref}</p>
          <div className="mt-0.5 flex items-baseline gap-3">
            <span className="tabular text-[30px] font-semibold leading-none tracking-[-0.02em]">{inr(amount)}</span>
            <span className="text-[14px] text-muted">
              {c.disputed ? 'Disputed transaction' : amount ? 'Amount reported by customer — not yet found in evidence' : 'Amount not yet established'}
            </span>
          </div>
          <p className="mt-1.5 text-[12.5px] text-muted">Filed {dateTime(c.created_at)}{c.analyzed_at && ` · analysed ${dateTime(c.analyzed_at)}`}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[12.5px] text-muted">Investigation status</span>
          <Badge tone={CASE_STATUS[c.status]?.tone} className="text-[12.5px]">{CASE_STATUS[c.status]?.label ?? c.status}</Badge>
          <select aria-label="Change case status" value="" disabled={status.isPending}
            onChange={e => e.target.value && status.mutate(e.target.value)}
            className="h-7 rounded-[var(--radius-sm)] border border-rule bg-surface px-1.5 text-[12.5px] text-ink-2">
            <option value="">Change…</option>
            {['UNDER_REVIEW', 'REPORT_READY', 'CLOSED'].filter(s => s !== c.status).map(s => <option key={s} value={s}>{CASE_STATUS[s].label}</option>)}
          </select>
        </div>
      </div>
      <nav className="mt-4 flex gap-0 border-b border-rule text-[13px]">
        {[['evidence', 'Evidence'], ['investigation', 'Investigation'], ['report', 'Report']].map(([p, l]) => (
          <NavLink key={p} to={`/cases/${c.id}/${p}`}
            className={({ isActive }) => cn('-mb-px border-b-2 border-transparent px-3 py-2 text-muted hover:text-ink', isActive && 'border-ink font-medium text-ink')}>
            {l}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
