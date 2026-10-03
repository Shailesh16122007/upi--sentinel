import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Button, ErrorNote, Field, inputCls, Panel, PageHead, selectCls } from '@/components/ui'
import { api } from '@/lib/api'
import { useAuth, useMe } from '@/lib/auth'

export default function Profile() {
  const me = useMe()
  const { refresh } = useAuth()
  const p = me.profile ?? {}
  const { data: banks = [] } = useQuery({ queryKey: ['banks'], queryFn: api.banks })
  const [form, setForm] = useState({ phone: p.phone ?? '', bank_name: p.bank_name ?? '', own_vpa: p.own_vpa ?? '', city: p.city ?? '' })
  const m = useMutation({ mutationFn: () => api.updateProfile(form), onSuccess: () => refresh() })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }))
  return (
    <div className="max-w-[560px]">
      <PageHead title="Profile" sub={`${me.name} · ${me.email} · User ID ${me.user_code}`} />
      <Panel>
        <form className="space-y-4 p-4" onSubmit={e => { e.preventDefault(); m.mutate() }}>
          <Field label="Mobile number" hint="used so we don't mistake your own number for a scammer's">
            <input className={inputCls} value={form.phone} onChange={set('phone')} inputMode="tel" /></Field>
          <Field label="Your bank" hint="new cases are sent here">
            <select className={selectCls + ' h-9 w-full'} value={form.bank_name} onChange={set('bank_name')}>
              <option value="">Choose…</option>{banks.map(b => <option key={b}>{b}</option>)}
            </select></Field>
          <Field label="Your own UPI ID" hint="optional"><input className={inputCls} value={form.own_vpa} onChange={set('own_vpa')} /></Field>
          <Field label="City" hint="optional"><input className={inputCls} value={form.city} onChange={set('city')} /></Field>
          {m.isError && <ErrorNote>{(m.error as Error).message}</ErrorNote>}
          {m.isSuccess && <p className="text-[13px] text-ok">Saved.</p>}
          <Button type="submit" variant="primary" disabled={m.isPending}>Save</Button>
        </form>
      </Panel>
    </div>
  )
}
