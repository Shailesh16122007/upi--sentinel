import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { CaseHeader } from '@/components/CaseHeader'
import { Button, ErrorNote, Panel, PanelHead } from '@/components/ui'
import { api, blobUrl } from '@/lib/api'
import { dateTime } from '@/lib/format'

const SECTIONS = ['Case information', 'Customer statement', 'Disputed transaction', 'Submitted evidence', 'Evidence extraction summary',
  'Timeline', 'Supporting evidence', 'Contradictory evidence', 'Contextual evidence', 'Anomalies', 'Evidence conflicts',
  'Missing evidence', 'Evidence completeness', 'Investigation summary', 'Investigator notes', 'Audit trail']

export default function CaseReport() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const { data: c } = useQuery({ queryKey: ['case', id], queryFn: () => api.case(id) })
  const { data: reports = [] } = useQuery({ queryKey: ['reports', id], queryFn: () => api.reports(id) })
  const [preview, setPreview] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const make = useMutation({
    mutationFn: () => api.makeReport(id),
    onSuccess: r => { qc.invalidateQueries({ queryKey: ['reports', id] }); qc.invalidateQueries({ queryKey: ['case', id] }); show(r.download_url) },
  })
  const show = (url: string) => blobUrl(url).then(u => { setPreview(old => { if (old) URL.revokeObjectURL(old); return u }) }).catch(e => setErr(e.message))
  useEffect(() => { if (reports[0] && !preview) show(reports[0].download_url) }, [reports]) // eslint-disable-line react-hooks/exhaustive-deps
  const download = async (url: string, name: string) => {
    try {
      const u = await blobUrl(url)
      const a = Object.assign(document.createElement('a'), { href: u, download: name })
      a.click()
      setTimeout(() => URL.revokeObjectURL(u), 2000)
    } catch (e) { setErr((e as Error).message) }
  }
  if (!c) return null
  return (
    <>
      <CaseHeader c={c} />
      <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-5">
          <Panel>
            <PanelHead title="Dispute report" sub="A PDF built from this case’s current evidence, findings, notes and audit trail." />
            <div className="space-y-3 px-4 py-3">
              {!c.analyzed_at && <ErrorNote>Analysis has not run yet — upload evidence first.</ErrorNote>}
              {make.isError && <ErrorNote>{(make.error as Error).message}</ErrorNote>}
              {err && <ErrorNote>{err}</ErrorNote>}
              <Button variant="primary" disabled={!c.analyzed_at || make.isPending} onClick={() => make.mutate()} className="w-full">
                {make.isPending ? 'Generating…' : reports.length ? 'Generate updated report' : 'Generate report'}
              </Button>
              <ol className="columns-1 text-[12.5px] text-muted">
                {SECTIONS.map((s, i) => <li key={s}><span className="tabular inline-block w-5 text-faint">{i + 1}.</span>{s}</li>)}
              </ol>
            </div>
          </Panel>
          {reports.length > 0 && (
            <Panel>
              <PanelHead title="Generated reports" />
              <ul className="divide-y divide-rule-2 text-[13px]">
                {reports.map(r => (
                  <li key={r.id} className="flex items-center justify-between gap-2 px-4 py-2">
                    <span><span className="block">{dateTime(r.created_at)}</span><span className="font-mono text-[11px] text-muted">{r.sha256.slice(0, 16)}…</span></span>
                    <span className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => show(r.download_url)}>View</Button>
                      <Button size="sm" onClick={() => download(r.download_url, `${c.ref}_report.pdf`)}>Download report</Button>
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
        <Panel className="min-h-[640px] overflow-hidden">
          {preview ? <iframe title="Report preview" src={preview} className="h-[80vh] w-full" />
            : <p className="p-6 text-[13px] text-muted">Generate the report to preview it here.</p>}
        </Panel>
      </div>
    </>
  )
}
