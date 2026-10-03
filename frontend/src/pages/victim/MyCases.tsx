import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Empty, Panel, PageHead } from '@/components/ui'
import { api } from '@/lib/api'
import { cn } from '@/lib/format'
import { CaseCard } from './Dashboard'

const FILTERS = [['all', 'All'], ['open', 'Open'], ['action', 'Action required'], ['resolved', 'Resolved']] as const

export default function MyCases() {
  const nav = useNavigate()
  const [p, setP] = useSearchParams()
  const f = p.get('filter') ?? 'all'
  const { data = [], isSuccess } = useQuery({ queryKey: ['cases', 'mine'], queryFn: () => api.cases(), refetchInterval: 15_000 })
  const list = data.filter(c => f === 'all' ? true : f === 'resolved' ? ['RESOLVED', 'CLOSED'].includes(c.status)
    : f === 'action' ? ['EVIDENCE_REQUESTED', 'DRAFT'].includes(c.status) : !['RESOLVED', 'CLOSED'].includes(c.status))
  return (
    <div>
      <PageHead title="My cases" aside={<Button variant="primary" onClick={() => nav('/my/cases/new')}>Report a fraud</Button>} />
      <div className="mb-4 flex flex-wrap gap-1">
        {FILTERS.map(([k, l]) => (
          <button key={k} onClick={() => setP(k === 'all' ? {} : { filter: k })}
            className={cn('rounded-[var(--radius-sm)] border px-3 py-1 text-[13px]', f === k ? 'border-accent bg-accent-tint text-accent-ink' : 'border-rule bg-surface text-ink-2')}>{l}</button>
        ))}
      </div>
      <div className="space-y-3">
        {list.map(c => <CaseCard key={c.id} c={c} />)}
        {isSuccess && !list.length && <Panel><Empty>No cases here.</Empty></Panel>}
      </div>
    </div>
  )
}
