import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { api } from '@/lib/api'
import { cn } from '@/lib/format'

function Capability({ ok, label, title }: { ok: boolean; label: string; title?: string }) {
  return (
    <span title={title} className="flex items-center gap-1.5 text-[12px] text-muted">
      <span className={cn('h-1.5 w-1.5 rounded-full', ok ? 'bg-ok' : 'bg-missing')} />{label}
    </span>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const { data: cap, isError } = useQuery({ queryKey: ['cap'], queryFn: api.capabilities, refetchInterval: 60_000 })
  const stt = cap?.speech_to_text
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex h-12 max-w-[1320px] items-center gap-6 px-5">
          <Link to="/" className="flex items-baseline gap-2">
            <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">UPI Sentinel</span>
          </Link>
          <nav className="flex gap-1 text-[13px]">
            {[['/cases', 'Cases'], ['/cases/new', 'New dispute']].map(([to, label]) => (
              <NavLink key={to} to={to} end
                className={({ isActive }) => cn('rounded-[var(--radius-sm)] px-2.5 py-1 text-ink-2 hover:bg-tint', isActive && 'bg-tint font-medium text-ink')}>
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-4 md:flex">
            {isError && <Capability ok={false} label="Server unreachable" />}
            {cap && <>
              <Capability ok={cap.ocr.available} label={cap.ocr.available ? 'OCR ready' : 'OCR unavailable'} />
              <Capability ok={!!stt?.enabled && !stt?.error} label={!stt?.enabled ? 'Speech-to-text off' : stt?.error ? 'Speech-to-text unavailable' : stt?.loaded ? 'Speech-to-text ready' : 'Speech-to-text loads on first use'}
                title={stt?.error ?? undefined} />
              <Capability ok label={cap.llm_summary.configured ? 'LLM summary on' : 'Deterministic summary'} />
            </>}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1320px] flex-1 px-5 py-6">{children}</main>
      <footer className="border-t border-rule px-5 py-3 text-center text-[12px] text-faint">
        UPI Sentinel organises evidence for review. Decisions on disputes are made by the authorised investigator.
      </footer>
    </div>
  )
}
