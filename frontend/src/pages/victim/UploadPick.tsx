import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Button, Empty, Panel, PageHead, StatusBadge } from '@/components/ui'
import { api } from '@/lib/api'
import { inr } from '@/lib/format'

export default function UploadPick() {
  const nav = useNavigate()
  const { data = [] } = useQuery({ queryKey: ['cases', 'mine'], queryFn: () => api.cases() })
  const open = data.filter(c => c.status !== 'CLOSED')
  return (
    <div className="max-w-[720px]">
      <PageHead title="Upload evidence" sub="Choose the case the proof belongs to, or start a new report." />
      <Panel>
        {!open.length && <Empty>You have no open cases.</Empty>}
        <ul className="divide-y divide-rule-2">
          {open.map(c => (
            <li key={c.id} className="flex items-center gap-3 px-4 py-3">
              <span className="font-mono text-[12.5px]">{c.ref}</span>
              <span className="tabular font-medium">{inr(c.disputed_amount ?? c.claimed_amount)}</span>
              <StatusBadge status={c.status} label={c.status_label} />
              <Button size="sm" className="ml-auto" onClick={() => nav(`/my/cases/${c.id}?step=upload`)}>Add proof</Button>
            </li>
          ))}
        </ul>
      </Panel>
      <Button className="mt-4" variant="primary" onClick={() => nav('/my/cases/new')}>Report a new fraud</Button>
    </div>
  )
}
