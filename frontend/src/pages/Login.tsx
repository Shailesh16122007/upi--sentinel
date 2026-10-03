import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, ErrorNote, Field, inputCls, Panel } from '@/components/ui'
import { api } from '@/lib/api'
import { homeFor, useAuth } from '@/lib/auth'

export default function Login() {
  const { signIn } = useAuth()
  const nav = useNavigate()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { data: demo = [] } = useQuery({ queryKey: ['demo-accounts'], queryFn: api.demoAccounts, retry: false })

  const go = async (l = login, p = password) => {
    setErr(null)
    setBusy(true)
    try {
      const a = await signIn(l, p)
      nav(homeFor(a.role), { replace: true })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full bg-paper">
      <div className="mx-auto grid max-w-[1000px] gap-10 px-4 py-12 md:grid-cols-[1.1fr_1fr] md:py-20">
        <section className="self-center">
          <p className="text-[13px] font-semibold tracking-[0.12em] text-ink">UPI SENTINEL</p>
          <h1 className="mt-3 text-[30px] font-semibold leading-tight tracking-[-0.015em] text-ink sm:text-[36px]">
            Digital payment dispute investigation
          </h1>
          <ul className="mt-5 space-y-1.5 text-[16px] text-ink-2">
            <li>Upload evidence.</li>
            <li>Understand what happened.</li>
            <li>Track your case.</li>
          </ul>
          <p className="mt-6 max-w-[46ch] text-[13.5px] text-muted">
            One case, one evidence trail — from the customer’s complaint, through the bank’s investigation, to the cyber crime authority.
          </p>
        </section>

        <section>
          <Panel>
            <form className="space-y-4 p-5" onSubmit={e => { e.preventDefault(); go() }}>
              <div>
                <h2 className="text-[17px] font-semibold">Sign in</h2>
                <p className="text-[13px] text-muted">Secure case management for digital payment disputes</p>
              </div>
              <Field label="Email or user ID">
                <input className={inputCls} value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" autoFocus />
              </Field>
              <Field label="Password">
                <input className={inputCls} type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" />
              </Field>
              {err && <ErrorNote>{err}</ErrorNote>}
              <Button type="submit" variant="primary" size="lg" className="w-full" disabled={busy || !login || !password}>
                {busy ? 'Signing in…' : 'Sign in'}
              </Button>
              <p className="text-[12px] text-faint">Your role (customer, bank or cyber crime) comes from your account.</p>
            </form>
          </Panel>

          {demo.length > 0 && (
            <Panel className="mt-4">
              <div className="border-b border-rule-2 px-4 py-2.5">
                <h3 className="text-[13.5px] font-semibold">Demo accounts</h3>
                <p className="text-[12px] text-muted">For trying the prototype. These are not real people or institutions.</p>
              </div>
              <ul className="divide-y divide-rule-2">
                {demo.map(d => (
                  <li key={d.email} className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]">
                    <span className="min-w-0">
                      <span className="block font-medium">{d.label}</span>
                      <span className="block truncate text-[12px] text-muted">{d.email} · {d.password}</span>
                    </span>
                    <Button size="sm" disabled={busy} onClick={() => { setLogin(d.email); setPassword(d.password); go(d.email, d.password) }}>
                      Sign in
                    </Button>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </section>
      </div>
    </div>
  )
}
