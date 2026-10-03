import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, ErrorNote, Field, inputCls, Panel } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'

export default function NewCase() {
  const me = useMe()
  const nav = useNavigate()
  const [statement, setStatement] = useState('')
  const [date, setDate] = useState('')
  const [amount, setAmount] = useState('')
  const [synthetic, setSynthetic] = useState(false)
  const create = useMutation({
    mutationFn: () => api.createCase({
      statement, approx_date: date || null, claimed_amount: amount ? Number(amount.replace(/[,₹\s]/g, '')) : null, synthetic,
    }),
    onSuccess: c => nav(`/my/cases/${c.id}?step=upload`),
  })
  const demo = useMutation({ mutationFn: api.loadDemo, onSuccess: r => nav(`/my/cases/${r.id}`) })
  const tooShort = statement.trim().length < 10

  return (
    <div className="mx-auto max-w-[640px]">
      <p className="text-[13px] text-muted">Report a fraud · step 1 of 3</p>
      <h1 className="mt-1 text-[26px] font-semibold tracking-[-0.01em]">What happened?</h1>
      <p className="mt-1 text-[14px] text-muted">Tell us in your own words. You don’t need transaction IDs or account details — we read those from your proof in the next step.</p>
      <Panel className="mt-5">
        <form className="space-y-4 p-4" onSubmit={e => { e.preventDefault(); if (!tooShort) create.mutate() }}>
          <Field label="Tell us what happened in your own words">
            <textarea className={inputCls + ' min-h-[140px] resize-y text-[15px]'} value={statement} onChange={e => setStatement(e.target.value)} autoFocus
              placeholder="For example: I received a call from someone claiming to be from my bank. Later ₹25,000 was transferred from my account." />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="About when did it happen?" hint="optional">
              <input type="date" className={inputCls} value={date} onChange={e => setDate(e.target.value)} />
            </Field>
            <Field label="About how much money?" hint="optional">
              <input inputMode="decimal" className={inputCls} placeholder="₹" value={amount} onChange={e => setAmount(e.target.value)} />
            </Field>
          </div>
          {me.is_demo && (
            <label className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-rule-2 bg-paper p-2.5 text-[12.5px]">
              <input type="checkbox" checked={synthetic} onChange={e => setSynthetic(e.target.checked)} className="mt-0.5" />
              <span><span className="font-medium">Mark as a synthetic demo case</span> — tick this only when uploading the demonstration files.
                Synthetic cases are labelled DEMO and never mixed with real cases. Leave it unticked for your own real evidence.</span>
            </label>
          )}
          {create.isError && <ErrorNote>{(create.error as Error).message}</ErrorNote>}
          <div className="flex items-center justify-between border-t border-rule-2 pt-4">
            <span className="text-[12.5px] text-muted">{tooShort ? 'Write at least one sentence to continue.' : ' '}</span>
            <Button type="submit" variant="primary" size="lg" disabled={tooShort || create.isPending}>
              {create.isPending ? 'Saving…' : 'Continue — upload your proof'}
            </Button>
          </div>
        </form>
      </Panel>
      {me.is_demo && (
        <div className="mt-4 rounded-[var(--radius-md)] border border-contra/25 bg-surface p-4 text-[13px]">
          <p className="font-medium">Demo shortcut</p>
          <p className="mt-0.5 text-muted">Create a fully synthetic example case (screenshot, bank SMS, chat, call recording and two bank exports) processed by the real pipeline.</p>
          {demo.isError && <div className="mt-2"><ErrorNote>{(demo.error as Error).message}</ErrorNote></div>}
          <Button className="mt-2" size="sm" onClick={() => demo.mutate()} disabled={demo.isPending}>
            {demo.isPending ? 'Processing synthetic files…' : 'Load synthetic example case'}
          </Button>
        </div>
      )}
    </div>
  )
}
