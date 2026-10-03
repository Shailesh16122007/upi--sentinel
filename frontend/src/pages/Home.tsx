import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { CaseTable } from '@/components/CaseTable'
import { Button, ErrorNote, Panel, PanelHead } from '@/components/ui'
import { api } from '@/lib/api'

const INPUTS = [
  ['Screenshots & images', 'UPI payment screens, bank SMS, chats, call history', 'PNG, JPG, WEBP'],
  ['Messages', 'Upload screenshots or paste the SMS text', 'Paste or TXT'],
  ['Audio', 'Recordings of the call you received', 'MP3, WAV, M4A, AAC'],
  ['Documents', 'Bank statements, complaint letters, emails saved as PDF', 'PDF, DOCX, TXT'],
]

export default function Home() {
  const nav = useNavigate()
  const { data: cases = [] } = useQuery({ queryKey: ['cases', 'real'], queryFn: () => api.cases(false) })
  const demo = useMutation({ mutationFn: api.loadDemo, onSuccess: r => nav(`/cases/${r.id}/investigation`) })

  return (
    <div className="space-y-8">
      <section className="grid gap-8 border-b border-rule pb-8 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <h1 className="text-[40px] font-semibold leading-[1.05] tracking-[-0.02em] text-ink sm:text-[48px]">UPI Sentinel</h1>
          <p className="mt-3 text-[20px] leading-snug text-ink-2">Reconstruct the transaction.<br />Understand the evidence.</p>
          <p className="mt-4 max-w-[52ch] text-[15px] text-muted">
            Upload whatever evidence you have. We’ll organise it into an investigation — what happened, in what order,
            what each piece of evidence says, and what is still missing.
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2">
            <Button variant="primary" size="lg" onClick={() => nav('/cases/new')}>Start a new dispute</Button>
            <Button size="lg" onClick={() => nav('/cases')}>Open existing case</Button>
          </div>
        </div>
        <div className="self-end">
          <p className="mb-2 text-[13px] font-medium text-ink">You don’t need to know file formats. Any of these will do:</p>
          <ul className="divide-y divide-rule-2 border-y border-rule-2">
            {INPUTS.map(([t, d, f]) => (
              <li key={t} className="grid grid-cols-[150px_1fr] gap-3 py-2 text-[13px]">
                <span className="font-medium">{t}</span>
                <span className="text-muted">{d} <span className="text-faint">· {f}</span></span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[12.5px] text-faint">Bank exports and device logs (CSV, JSON) can be added under advanced evidence.</p>
        </div>
      </section>

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_320px]">
        <Panel>
          <PanelHead title="Recent disputes" sub={cases.length ? undefined : 'Disputes you create will appear here.'} />
          {cases.length > 0 && <CaseTable cases={cases.slice(0, 8)} />}
        </Panel>
        <Panel className="h-fit border-contra/25">
          <PanelHead title="Synthetic demo case" />
          <div className="space-y-3 px-4 py-3 text-[13px] text-muted">
            <p>Loads a fully synthetic dispute — UPI screenshot, bank SMS, call recording with transcript, 60-row transaction
              history and an account activity log — and runs it through the same pipeline as real uploads.</p>
            <p className="font-medium text-contra">Labelled synthetic demonstration data. Kept separate from real cases.</p>
            {demo.isError && <ErrorNote>{(demo.error as Error).message}</ErrorNote>}
            <Button onClick={() => demo.mutate()} disabled={demo.isPending}>
              {demo.isPending ? 'Processing demo evidence…' : 'Load synthetic demo case'}
            </Button>
          </div>
        </Panel>
      </div>
    </div>
  )
}
