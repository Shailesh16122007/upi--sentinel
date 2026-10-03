import { useQuery } from '@tanstack/react-query'
import { Bell, Menu, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api } from '@/lib/api'
import { useMe, useAuth } from '@/lib/auth'
import { cn, when } from '@/lib/format'
import type { Account } from '@/lib/types'

type Item = { to: string; label: string; end?: boolean }
const NAV: Record<Account['role'], Item[]> = {
  VICTIM: [
    { to: '/my', label: 'Dashboard', end: true }, { to: '/my/cases', label: 'My cases' }, { to: '/my/upload', label: 'Upload evidence' },
    { to: '/my/notifications', label: 'Notifications' }, { to: '/my/profile', label: 'Profile' },
  ],
  BANK: [
    { to: '/bank', label: 'Dashboard', end: true }, { to: '/bank/cases', label: 'Cases' }, { to: '/bank/requests', label: 'Evidence requests' },
    { to: '/bank/related', label: 'Related cases' }, { to: '/bank/network', label: 'Mule network' }, { to: '/bank/reports', label: 'Reports' },
    { to: '/bank/audit', label: 'Audit' },
  ],
  CYBER: [
    { to: '/cyber', label: 'Dashboard', end: true }, { to: '/cyber/cases', label: 'Cases' }, { to: '/cyber/escalated', label: 'Escalated' },
    { to: '/cyber/related', label: 'Related cases' }, { to: '/cyber/network', label: 'Mule network' }, { to: '/cyber/reports', label: 'Reports' },
    { to: '/cyber/closed', label: 'Closed cases' }, { to: '/cyber/audit', label: 'Audit' },
  ],
}
const ROLE_LINE: Record<Account['role'], string> = { VICTIM: 'Customer', BANK: 'Bank investigation', CYBER: 'Cyber crime authority' }

function Bellbutton({ base }: { base: string }) {
  const nav = useNavigate()
  const { data } = useQuery({ queryKey: ['notifications'], queryFn: api.notifications, refetchInterval: 15_000 })
  const [open, setOpen] = useState(false)
  const items = data?.items.slice(0, 8) ?? []
  return (
    <div className="relative">
      <button aria-label={`Notifications${data?.unread ? `, ${data.unread} unread` : ''}`} onClick={() => setOpen(o => !o)}
        className="relative flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] text-ink-2 hover:bg-tint">
        <Bell className="h-4 w-4" />
        {!!data?.unread && <span className="tabular absolute -right-0.5 -top-0.5 min-w-[16px] rounded-full bg-contra px-1 text-[10px] font-semibold leading-4 text-white">{data.unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-[340px] max-w-[calc(100vw-24px)] rounded-[var(--radius-md)] border border-rule bg-surface shadow-[0_8px_24px_rgba(19,35,63,0.12)]">
          <div className="flex items-center justify-between border-b border-rule-2 px-3 py-2 text-[13px]">
            <span className="font-semibold">Notifications</span>
            <button className="text-accent hover:underline" onClick={() => { setOpen(false); nav(`${base}/notifications`) }}>View all</button>
          </div>
          {!items.length && <p className="px-3 py-4 text-[13px] text-muted">No notifications yet.</p>}
          <ul className="max-h-[360px] divide-y divide-rule-2 overflow-y-auto">
            {items.map(n => (
              <li key={n.id}>
                <button className="block w-full px-3 py-2 text-left hover:bg-tint" onClick={() => {
                  setOpen(false)
                  api.markRead([n.id]).catch(() => {})
                  if (n.case_id) nav(`${base}/cases/${n.case_id}`)
                }}>
                  <span className={cn('block text-[13px]', !n.read && 'font-semibold')}>{n.title}</span>
                  {n.body && <span className="block truncate text-[12px] text-muted">{n.body}</span>}
                  <span className="text-[11.5px] text-faint">{when(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe()
  const { signOut } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [menuAt, setMenuAt] = useState<string | null>(null)
  const menu = menuAt === loc.pathname  // closes by itself when the route changes
  const setMenu = (f: (m: boolean) => boolean) => setMenuAt(f(menu) ? loc.pathname : null)
  const base = me.role === 'VICTIM' ? '/my' : me.role === 'BANK' ? '/bank' : '/cyber'
  const items = NAV[me.role]
  const staff = me.role !== 'VICTIM'

  const links = (
    <nav className={cn('flex gap-0.5 text-[13.5px]', staff ? 'flex-col' : 'flex-col md:flex-row md:items-center')}>
      {items.map(i => (
        <NavLink key={i.to} to={i.to} end={i.end}
          className={({ isActive }) => cn('rounded-[var(--radius-sm)] px-2.5 py-1.5 text-ink-2 hover:bg-tint',
            isActive && 'bg-tint font-medium text-ink', staff && isActive && 'bg-accent-tint text-accent-ink')}>
          {i.label}
        </NavLink>
      ))}
    </nav>
  )
  const brand = (
    <Link to={base} className="flex flex-col leading-tight">
      <span className="text-[14px] font-semibold tracking-[0.04em] text-ink">UPI SENTINEL</span>
      <span className="text-[11px] text-muted">{ROLE_LINE[me.role]}</span>
    </Link>
  )
  const userBox = (
    <div className="flex items-center gap-2 text-[12.5px]">
      <span className="hidden text-right leading-tight sm:block">
        <span className="block font-medium text-ink">{me.name}</span>
        <span className="block text-muted">{me.org ?? me.user_code}{me.is_demo ? ' · demo account' : ''}</span>
      </span>
      <button className="rounded-[var(--radius-sm)] border border-rule px-2 py-1 text-ink-2 hover:bg-tint"
        onClick={async () => { await signOut(); nav('/') }}>Sign out</button>
    </div>
  )

  if (!staff) {
    return (
      <div className="flex min-h-full flex-col">
        <header className="border-b border-rule bg-surface">
          <div className="mx-auto flex h-14 max-w-[1080px] items-center gap-5 px-4">
            {brand}
            <div className="hidden flex-1 md:block">{links}</div>
            <div className="ml-auto flex items-center gap-2">
              <Bellbutton base={base} />
              <div className="hidden md:block">{userBox}</div>
              <button className="md:hidden" aria-label="Menu" onClick={() => setMenu(m => !m)}>{menu ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}</button>
            </div>
          </div>
          {menu && <div className="space-y-3 border-t border-rule-2 px-4 py-3 md:hidden">{links}{userBox}</div>}
        </header>
        <main className="mx-auto w-full max-w-[1080px] flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-rule px-4 py-3 text-center text-[12px] text-faint">
          UPI Sentinel helps you organise your proof. Decisions on your case are made by your bank and the authorities.
        </footer>
      </div>
    )
  }
  return (
    <div className="flex min-h-full">
      <aside className={cn('fixed inset-y-0 left-0 z-30 w-[220px] flex-col border-r border-rule bg-surface px-3 py-4 lg:flex',
        menu ? 'flex' : 'hidden')}>
        <div className="mb-5 px-1">{brand}</div>
        {links}
        <div className="mt-auto space-y-1 border-t border-rule-2 px-1 pt-3 text-[12px] text-muted">
          <div className="font-medium text-ink-2">{me.name}</div>
          <div>{me.org}</div>
          {me.is_demo && <div className="text-missing">Demo account</div>}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col lg:pl-[220px]">
        <header className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b border-rule bg-surface px-4">
          <button className="lg:hidden" aria-label="Menu" onClick={() => setMenu(m => !m)}>{menu ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}</button>
          <SearchBox base={base} />
          <div className="ml-auto flex items-center gap-3"><Bellbutton base={base} />{userBox}</div>
        </header>
        <main className="w-full min-w-0 flex-1 px-4 py-5 lg:px-6">{children}</main>
        <footer className="border-t border-rule px-4 py-2 text-[12px] text-faint">
          System findings support the investigation. Decisions rest with the authorised investigator.
        </footer>
      </div>
    </div>
  )
}

function SearchBox({ base }: { base: string }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  return (
    <form className="w-full max-w-[420px]" onSubmit={e => { e.preventDefault(); if (q.trim().length >= 2) nav(`${base}/cases?q=${encodeURIComponent(q.trim())}`) }}>
      <input value={q} onChange={e => setQ(e.target.value)} aria-label="Search cases"
        placeholder="Search case ID, UTR, UPI ID, phone, amount, date…"
        className="h-8 w-full rounded-[var(--radius-sm)] border border-rule bg-paper px-2.5 text-[13px] placeholder:text-faint focus:border-accent focus:bg-surface focus:outline-none" />
    </form>
  )
}
