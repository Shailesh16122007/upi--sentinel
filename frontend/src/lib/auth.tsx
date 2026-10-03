import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, token } from './api'
import type { Account } from './types'

type Ctx = {
  account: Account | null
  ready: boolean
  signIn: (login: string, password: string) => Promise<Account>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
}
const AuthCtx = createContext<Ctx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [account, setAccount] = useState<Account | null>(null)
  const [ready, setReady] = useState(false)

  const refresh = useCallback(async () => {
    if (!token.get()) { setAccount(null); setReady(true); return }
    try { setAccount(await api.me()) } catch { token.clear(); setAccount(null) }
    setReady(true)
  }, [])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => {
    const out = () => { token.clear(); setAccount(null); qc.clear() }
    window.addEventListener('sentinel:signed-out', out)
    return () => window.removeEventListener('sentinel:signed-out', out)
  }, [qc])

  const signIn = async (login: string, password: string) => {
    const r = await api.login(login, password)
    token.set(r.token)
    qc.clear()
    setAccount(r.account)
    return r.account
  }
  const signOut = async () => {
    try { await api.logout() } catch { /* already gone */ }
    token.clear()
    qc.clear()
    setAccount(null)
  }
  return <AuthCtx.Provider value={{ account, ready, signIn, signOut, refresh }}>{children}</AuthCtx.Provider>
}

export function useAuth() {
  const c = useContext(AuthCtx)
  if (!c) throw new Error('AuthProvider missing')
  return c
}

/** The signed-in account (only use inside routes that require sign-in). */
export function useMe(): Account {
  const { account } = useAuth()
  if (!account) throw new Error('Not signed in')
  return account
}

export const homeFor = (role: Account['role']) => (role === 'VICTIM' ? '/my' : role === 'BANK' ? '/bank' : '/cyber')
