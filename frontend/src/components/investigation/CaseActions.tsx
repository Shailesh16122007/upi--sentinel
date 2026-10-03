import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Badge, Button, Dialog, ErrorNote, Field, inputCls, Panel, PanelHead, selectCls } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { dateTime, when } from '@/lib/format'
import type { AllowedAction, CaseFull } from '@/lib/types'
import { NotesView } from './Records'

function useRefresh(id: string) {
  const qc = useQueryClient()
  return () => { qc.invalidateQueries({ queryKey: ['case', id] }); qc.invalidateQueries({ queryKey: ['actions', id] });
    qc.invalidateQueries({ queryKey: ['requests', id] }); qc.invalidateQueries({ queryKey: ['audit', id] }); qc.invalidateQueries({ queryKey: ['cases'] }) }
}

function Transition({ c, a }: { c: CaseFull; a: AllowedAction }) {
  const refresh = useRefresh(c.id)
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const m = useMutation({ mutationFn: () => api.act(c.id, a.action, note), onSuccess: () => { setOpen(false); setNote(''); refresh() } })
  const primary = ['escalate', 'cyber_accept', 'start_review', 'cyber_investigate'].includes(a.action)
  return (
    <>
      <Button variant={primary ? 'primary' : 'secondary'} onClick={() => setOpen(true)}>{a.label}</Button>
      <Dialog open={open} onOpenChange={setOpen} title={a.label}>
        <form className="space-y-3" onSubmit={e => { e.preventDefault(); m.mutate() }}>
          <p className="text-[13px] text-muted">The case will move to <span className="font-medium text-ink">“{a.to.replace(/_/g, ' ').toLowerCase()}”</span>. This is recorded in the audit trail{['escalate', 'bank_resolve', 'bank_close', 'cyber_resolve', 'cyber_close'].includes(a.action) ? ' and the customer is notified' : ''}.</p>
          <Field label={a.note_required ? 'Reason (required)' : 'Note (optional)'}>
            <textarea className={inputCls + ' min-h-[90px]'} value={note} onChange={e => setNote(e.target.value)} autoFocus />
          </Field>
          {m.isError && <ErrorNote>{(m.error as Error).message}</ErrorNote>}
          <div className="flex gap-2"><Button type="submit" variant="primary" disabled={m.isPending || (a.note_required && !note.trim())}>Confirm</Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button></div>
        </form>
      </Dialog>
    </>
  )
}

function Dispositions({ c }: { c: CaseFull }) {
  const refresh = useRefresh(c.id)
  const { data: opts } = useQuery({ queryKey: ['status-options'], queryFn: api.statusOptions })
  const d = c.dispositions!
  const [form, setForm] = useState({ bank_outcome: d.bank_outcome ?? '', account_action: d.account_action ?? '', reversal_status: d.reversal_status ?? '', priority: d.priority })
  const [note, setNote] = useState('')
  const m = useMutation({
    mutationFn: () => api.dispositions(c.id, { ...Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v || null])), note: note || null }),
    onSuccess: () => { setNote(''); refresh() },
  })
  const sel = (k: keyof typeof form, cat: string, label: string) => (
    <Field label={label}>
      <select className={selectCls + ' w-full'} value={form[k]} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))}>
        <option value="">Not set</option>{(opts?.[cat] ?? []).map(o => <option key={o.code} value={o.code}>{o.label}</option>)}
      </select>
    </Field>
  )
  const disabled = ['DRAFT', 'CLOSED'].includes(c.status)
  return (
    <Panel>
      <PanelHead title="Bank actions" sub="Outcome, account action and reversal status. Options are configurable per bank. Reversal updates are shown to the customer." />
      <form className="grid gap-3 px-4 py-3 sm:grid-cols-2" onSubmit={e => { e.preventDefault(); m.mutate() }}>
        {sel('bank_outcome', 'BANK_OUTCOME', 'Bank outcome')}
        {sel('account_action', 'ACCOUNT_ACTION', 'Account action')}
        {sel('reversal_status', 'REVERSAL', 'Payment reversal / reimbursement')}
        <Field label="Priority">
          <select className={selectCls + ' w-full'} value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}>
            <option value="NORMAL">Normal</option><option value="HIGH">High</option></select>
        </Field>
        <div className="sm:col-span-2"><Field label="Note (optional)"><input className={inputCls} value={note} onChange={e => setNote(e.target.value)} /></Field></div>
        {m.isError && <div className="sm:col-span-2"><ErrorNote>{(m.error as Error).message}</ErrorNote></div>}
        <div className="sm:col-span-2"><Button type="submit" variant="primary" disabled={disabled || m.isPending}>Record bank action</Button></div>
      </form>
    </Panel>
  )
}

function Requests({ c }: { c: CaseFull }) {
  const me = useMe()
  const refresh = useRefresh(c.id)
  const { data: items = [] } = useQuery({ queryKey: ['request-items'], queryFn: api.requestItems })
  const { data: reqs = [] } = useQuery({ queryKey: ['requests', c.id], queryFn: () => api.requests(c.id), refetchInterval: 10_000 })
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const [msg, setMsg] = useState('')
  const [reply, setReply] = useState<Record<string, string>>({})
  const create = useMutation({ mutationFn: () => api.createRequest(c.id, picked, msg), onSuccess: () => { setOpen(false); setPicked([]); setMsg(''); refresh() } })
  const respond = useMutation({ mutationFn: (id: string) => api.respond(id, reply[id]), onSuccess: () => refresh() })
  const toBank = me.role === 'CYBER'
  const canAsk = toBank ? ['ESCALATED', 'CYBER_REVIEW', 'UNDER_INVESTIGATION', 'PENDING'].includes(c.status)
    : ['SUBMITTED', 'BANK_REVIEW'].includes(c.status) && !c.with_cyber
  return (
    <Panel>
      <PanelHead title={toBank ? 'Information requests to the bank' : 'Evidence requests'}
        sub={toBank ? 'Ask the bank for records or clarification. The case returns to you when the bank responds.'
          : 'Ask the customer for more proof. The case returns to bank review automatically when they upload it.'}
        aside={<Button size="sm" disabled={!canAsk} onClick={() => setOpen(true)}>{toBank ? 'Request information' : 'Request more evidence'}</Button>} />
      <ul className="divide-y divide-rule-2">
        {!reqs.length && <li className="px-4 py-3 text-[13px] text-muted">No requests.</li>}
        {reqs.map(r => (
          <li key={r.id} className="px-4 py-2.5 text-[13px]">
            <div className="flex flex-wrap items-center gap-2"><Badge tone={r.status === 'OPEN' ? 'warn' : 'ok'}>{r.status === 'OPEN' ? 'Open' : 'Answered'}</Badge>
              <span className="font-medium">{r.target_role === 'VICTIM' ? 'To customer' : 'To bank'}:</span> {r.items.join(', ')}
              <span className="text-muted">· {r.requested_by} · {when(r.created_at)}</span></div>
            <p className="mt-0.5 text-ink-2">“{r.message}”</p>
            {r.fulfilled_at && <p className="text-muted">Answered {dateTime(r.fulfilled_at)}{r.evidence.length ? ` with ${r.evidence.map(e => e.code).join(', ')}` : ''}{r.response_note ? ` — “${r.response_note}”` : ''}</p>}
            {r.status === 'OPEN' && r.target_role === me.role && (
              <div className="mt-1.5 flex gap-2">
                <input className={inputCls + ' text-[13px]'} placeholder="Describe the information provided" value={reply[r.id] ?? ''} onChange={e => setReply(x => ({ ...x, [r.id]: e.target.value }))} />
                <Button size="sm" variant="primary" disabled={!(reply[r.id] ?? '').trim() || respond.isPending} onClick={() => respond.mutate(r.id)}>Respond</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {respond.isError && <div className="px-4 pb-3"><ErrorNote>{(respond.error as Error).message}</ErrorNote></div>}
      <Dialog open={open} onOpenChange={setOpen} title={toBank ? 'Request information from the bank' : 'Request more evidence from the customer'}>
        <form className="space-y-3" onSubmit={e => { e.preventDefault(); create.mutate() }}>
          <fieldset className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {items.map(i => (
              <label key={i} className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={picked.includes(i)}
                onChange={e => setPicked(p => e.target.checked ? [...p, i] : p.filter(x => x !== i))} />{i}</label>
            ))}
          </fieldset>
          <Field label={toBank ? 'Message to the bank' : 'Message to the customer (plain language)'}>
            <textarea className={inputCls + ' min-h-[90px]'} value={msg} onChange={e => setMsg(e.target.value)}
              placeholder={toBank ? 'Please share the device-binding and login logs for 01 Oct 22:00–23:00.' : 'Please upload the bank statement showing the disputed transaction.'} />
          </Field>
          {create.isError && <ErrorNote>{(create.error as Error).message}</ErrorNote>}
          <Button type="submit" variant="primary" disabled={!picked.length || msg.trim().length < 5 || create.isPending}>Send request</Button>
        </form>
      </Dialog>
    </Panel>
  )
}

function History({ id }: { id: string }) {
  const { data = [] } = useQuery({ queryKey: ['actions', id], queryFn: () => api.actions(id) })
  return (
    <Panel>
      <PanelHead title="Action history" />
      <ul className="divide-y divide-rule-2 text-[13px]">
        {!data.length && <li className="px-4 py-3 text-muted">No actions yet.</li>}
        {data.map((a, i) => (
          <li key={i} className="px-4 py-2">
            <div className="flex flex-wrap gap-x-3"><span className="text-muted">{dateTime(a.at)}</span><span className="font-medium">{a.label}</span>
              {a.to_label && <span className="text-muted">→ {a.to_label}</span>}<span className="text-faint">{a.actor} · {a.role === 'VICTIM' ? 'Customer' : a.role}</span></div>
            {a.action === 'disposition' && a.detail && <div className="text-ink-2">{Object.values(a.detail).map((x: any) => x.label).join(', ')}</div>}
            {a.note && <p className="text-ink-2">“{a.note}”</p>}
          </li>
        ))}
      </ul>
    </Panel>
  )
}

export function CaseActions({ c }: { c: CaseFull }) {
  const me = useMe()
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <div className="space-y-5">
        <Panel>
          <PanelHead title="Case status" sub="Only transitions allowed from the current state are offered. Each one is validated on the server and audited." />
          <div className="flex flex-wrap gap-2 px-4 py-3">
            {c.allowed_actions.length ? c.allowed_actions.map(a => <Transition key={a.action} c={c} a={a} />)
              : <p className="text-[13px] text-muted">No status changes are available to you in the current state.</p>}
          </div>
        </Panel>
        <Requests c={c} />
        {me.role === 'BANK' && <Dispositions c={c} />}
      </div>
      <div className="space-y-5">
        <NotesView caseId={c.id} />
        <History id={c.id} />
      </div>
    </div>
  )
}
