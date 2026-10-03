import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, ErrorNote, Field, inputCls, Panel } from '@/components/ui'
import { api } from '@/lib/api'

export default function NewCase() {
  const nav = useNavigate()
  const [statement, setStatement] = useState('')
  const [date, setDate] = useState('')
  const [amount, setAmount] = useState('')
  const create = useMutation({
    mutationFn: () => api.createCase({
      statement, approx_date: date || null, claimed_amount: amount ? Number(amount.replace(/[,₹\s]/g, '')) : null,
    }),
    onSuccess: c => nav(`/cases/${c.id}/evidence`),
  })
  const tooShort = statement.trim().length < 10

  return (
    <div className="mx-auto max-w-[640px]">
      <p className="text-[13px] text-muted">New dispute · step 1 of 2</p>
      <h1 className="mt-1 text-[26px] font-semibold tracking-[-0.01em]">What happened?</h1>
      <p className="mt-1 text-[14px] text-muted">A few sentences in your own words is enough. Transaction IDs, times and account details will be read from your evidence in the next step.</p>
      <Panel className="mt-5">
        <form className="space-y-4 p-4" onSubmit={e => { e.preventDefault(); if (!tooShort) create.mutate() }}>
          <Field label="Tell us briefly what happened">
            <textarea className={inputCls + ' min-h-[130px] resize-y'} value={statement} onChange={e => setStatement(e.target.value)} autoFocus
              placeholder="For example: ₹25,000 was transferred from my account. I did not intend to make this payment." />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Approximate date" hint="optional">
              <input type="date" className={inputCls} value={date} onChange={e => setDate(e.target.value)} />
            </Field>
            <Field label="Amount, if you know it" hint="optional">
              <input inputMode="decimal" className={inputCls} placeholder="₹" value={amount} onChange={e => setAmount(e.target.value)} />
            </Field>
          </div>
          {create.isError && <ErrorNote>{(create.error as Error).message}</ErrorNote>}
          <div className="flex items-center justify-between border-t border-rule-2 pt-4">
            <span className="text-[12.5px] text-muted">{tooShort ? 'Write at least a sentence to continue.' : ' '}</span>
            <Button type="submit" variant="primary" disabled={tooShort || create.isPending}>
              {create.isPending ? 'Creating…' : 'Continue to upload evidence'}
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  )
}
