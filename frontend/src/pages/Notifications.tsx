import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Button, Empty, Panel, PageHead } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { cn, when } from '@/lib/format'

export default function Notifications() {
  const me = useMe()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['notifications'], queryFn: api.notifications, refetchInterval: 15_000 })
  const read = useMutation({ mutationFn: () => api.markRead(), onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }) })
  const base = me.role === 'VICTIM' ? '/my' : me.role === 'BANK' ? '/bank' : '/cyber'
  return (
    <div className="max-w-[820px]">
      <PageHead title="Notifications" sub={data ? `${data.unread} unread` : undefined}
        aside={<Button size="sm" disabled={!data?.unread || read.isPending} onClick={() => read.mutate()}>Mark all as read</Button>} />
      <Panel>
        {!data?.items.length && <Empty>No notifications yet.</Empty>}
        <ul className="divide-y divide-rule-2">
          {data?.items.map(n => (
            <li key={n.id}>
              <button className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-tint" onClick={() => {
                api.markRead([n.id]).then(() => qc.invalidateQueries({ queryKey: ['notifications'] }))
                if (n.case_id) nav(`${base}/cases/${n.case_id}`)
              }}>
                <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', n.read ? 'bg-transparent' : 'bg-accent')} />
                <span className="min-w-0 flex-1">
                  <span className={cn('block text-[14px]', !n.read && 'font-semibold')}>{n.title}</span>
                  {n.body && <span className="block text-[13px] text-muted">{n.body}</span>}
                </span>
                <span className="shrink-0 text-[12px] text-faint">{when(n.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
