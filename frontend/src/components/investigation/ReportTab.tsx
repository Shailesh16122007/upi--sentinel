import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Badge, Button, ErrorNote, Panel, PanelHead } from '@/components/ui'
import { api, blobUrl, download } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { dateTime } from '@/lib/format'
import type { CaseFull } from '@/lib/types'

const SECTIONS = ['Key findings', 'Case summary', 'Customer statement', 'Transaction details', 'Evidence received', 'Reconstructed timeline',
  'Important findings', 'Supporting evidence', 'Contradictory evidence', 'Evidence conflicts', 'Missing evidence',
  'Transaction history analysis', 'Device / session analysis', 'Beneficiary analysis', 'Related cases', 'Mule network findings',
  'Investigation notes', 'Case actions', 'Recommended next investigation steps', 'Audit trail']

export function ReportTab({ c }: { c: CaseFull }) {
  const me = useMe()
  const qc = useQueryClient()
  const audience = me.role === 'BANK' ? 'BANK' : 'CYBER'
  const { data: reps = [] } = useQuery({ queryKey: ['reports', c.id], queryFn: () => api.reports(c.id) })
  const pdfs = reps.filter(r => r.audience === audience)
  const [preview, setPreview] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const show = (url: string) => blobUrl(url).then(u => setPreview(old => { if (old) URL.revokeObjectURL(old); return u })).catch(e => setErr(e.message))
  const make = useMutation({ mutationFn: () => api.makeReport(c.id, audience),
    onSuccess: r => { qc.invalidateQueries({ queryKey: ['reports', c.id] }); qc.invalidateQueries({ queryKey: ['audit', c.id] }); show(r.download_url) } })
  useEffect(() => { if (pdfs[0] && !preview) show(pdfs[0].download_url) }, [pdfs.length]) // eslint-disable-line react-hooks/exhaustive-deps
  const exp = useQuery({ queryKey: ['export', c.id, c.analyzed_at, c.status], queryFn: () => api.exportPreview(c.id), enabled: me.role === 'CYBER' })

  return (
    <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
      <div className="space-y-5">
        <Panel>
          <PanelHead title={me.role === 'BANK' ? 'Bank investigation report' : 'Cyber crime investigation report'}
            sub="Built from the current case: latest evidence, timeline, findings, notes and status. Every statement cites its evidence. Earlier versions are kept." />
          <div className="space-y-3 px-4 py-3">
            {(make.isError || err) && <ErrorNote>{err ?? (make.error as Error).message}</ErrorNote>}
            <Button variant="primary" className="w-full" disabled={!c.analyzed_at || make.isPending} onClick={() => make.mutate()}>
              {make.isPending ? 'Generating…' : pdfs.length ? 'Generate new version' : 'Generate report'}</Button>
            {pdfs[0] && !pdfs[0].is_current && <p className="text-[12.5px] text-missing">The case changed after version {pdfs[0].version}. Generate a new version.</p>}
            <details className="text-[12.5px] text-muted"><summary className="cursor-pointer">Sections</summary>
              <ol className="mt-1">{SECTIONS.map((s, i) => <li key={s}><span className="tabular inline-block w-5 text-faint">{i + 1}.</span>{s}</li>)}
                {me.role === 'CYBER' && <li><span className="inline-block w-5 text-faint">+</span>Structured export</li>}</ol></details>
          </div>
        </Panel>
        {pdfs.length > 0 && (
          <Panel>
            <PanelHead title="Versions" />
            <ul className="divide-y divide-rule-2 text-[13px]">
              {pdfs.map(r => (
                <li key={r.id} className="px-4 py-2">
                  <div className="flex items-center gap-2"><span className="font-medium">Version {r.version}</span>
                    {r.is_current ? <Badge tone="ok">Current</Badge> : <Badge tone="outline">Superseded</Badge>}</div>
                  <div className="text-[12px] text-muted">{dateTime(r.created_at)} · {r.evidence_count} evidence items · {r.status_label}</div>
                  {r.changes && <div className="text-[12px] text-muted">Changes: {r.changes}</div>}
                  <div className="mt-1 flex gap-1"><Button size="sm" variant="ghost" onClick={() => show(r.download_url)}>View</Button>
                    <Button size="sm" onClick={() => download(r.download_url, `${c.ref}_${r.audience.toLowerCase()}_v${r.version}.pdf`)}>Download</Button></div>
                </li>
              ))}
            </ul>
          </Panel>
        )}
        {me.role === 'CYBER' && (
          <Panel>
            <PanelHead title="Cyber crime reporting export" sub="Structured export for manual entry / integration. Not an official NCRP / CFCFRMS submission." />
            <div className="space-y-2 px-4 py-3 text-[13px]">
              {exp.data && (
                <dl className="grid grid-cols-[130px_1fr] gap-y-1 text-[12.5px]">
                  {([['Amount', exp.data.transaction.amount_inr], ['UTR / reference', exp.data.transaction.utr_or_reference],
                    ['Beneficiary UPI', exp.data.transaction.beneficiary_upi_id], ['Beneficiary account', exp.data.transaction.beneficiary_account],
                    ['Suspect numbers', Array.isArray(exp.data.suspect_contact_numbers) ? exp.data.suspect_contact_numbers.join(', ') : exp.data.suspect_contact_numbers],
                    ['Related cases', String(exp.data.related_cases.length)], ['Evidence refs', String(exp.data.evidence_references.length)]] as [string, any][]).map(([k, v]) => (
                    <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="break-words">{String(v)}</dd></div>))}
                </dl>
              )}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => download(api.exportUrl(c.id), `${c.ref}_structured_export.json`).then(() => qc.invalidateQueries({ queryKey: ['audit', c.id] })).catch(e => setErr(e.message))}>Download structured JSON</Button>
                <Button size="sm" onClick={() => pdfs[0] ? download(pdfs[0].download_url, `${c.ref}_cyber_v${pdfs[0].version}.pdf`) : make.mutate()}>Download structured report</Button>
              </div>
              <p className="text-[12px] text-faint">The structured report is the cyber crime PDF, which ends with the export fields.</p>
            </div>
          </Panel>
        )}
      </div>
      <Panel className="min-h-[640px] overflow-hidden">
        {preview ? <iframe title="Report preview" src={preview} className="h-[80vh] w-full" />
          : <p className="p-6 text-[13px] text-muted">Generate the report to preview it here.</p>}
      </Panel>
    </div>
  )
}
