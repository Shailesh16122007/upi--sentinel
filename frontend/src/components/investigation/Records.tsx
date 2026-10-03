import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { EvidenceStatus, useSources } from '@/components/evidence'
import { Badge, Button, ErrorNote, inputCls, Panel, PanelHead } from '@/components/ui'
import { api } from '@/lib/api'
import { bytes, dateTime, humanize, kindLabel, methodLabel } from '@/lib/format'

export function SourcesView({ caseId }: { caseId: string }) {
  const { evidence, open } = useSources()
  return (
    <Panel>
      <PanelHead title={`Evidence sources (${evidence.length})`} sub="Originals are stored unchanged with a SHA-256 fingerprint. Select a row to inspect the original and what was extracted."
        aside={<Link to={`/cases/${caseId}/evidence`} className="text-[12.5px] text-accent hover:underline">Add evidence</Link>} />
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead><tr className="border-b border-rule text-left text-[12px] text-muted">
            {['Code', 'File', 'Type', 'Read with', 'Items found', 'Status', 'Received', 'SHA-256'].map(h => <th key={h} className="px-3 py-2 font-medium first:pl-4">{h}</th>)}
          </tr></thead>
          <tbody>
            {evidence.map(e => (
              <tr key={e.id} tabIndex={0} onClick={() => open({ evidenceId: e.id })} onKeyDown={k => k.key === 'Enter' && open({ evidenceId: e.id })}
                className="cursor-pointer border-b border-rule-2 align-top hover:bg-tint">
                <td className="px-3 py-2 pl-4 font-mono text-[12.5px] font-medium text-accent-ink">{e.code}</td>
                <td className="px-3 py-2">{e.original_name}{e.is_synthetic && <Badge tone="bad" className="ml-1.5">Synthetic</Badge>}</td>
                <td className="px-3 py-2">{kindLabel(e)}</td>
                <td className="px-3 py-2 text-muted">{methodLabel(e.method)}</td>
                <td className="tabular px-3 py-2">{e.entities.length}</td>
                <td className="px-3 py-2"><EvidenceStatus status={e.status} /></td>
                <td className="whitespace-nowrap px-3 py-2 text-muted">{dateTime(e.uploaded_at)} · {bytes(e.size_bytes)}</td>
                <td className="px-3 py-2 font-mono text-[11px] text-muted">{e.sha256?.slice(0, 16)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

export function NotesView({ caseId }: { caseId: string }) {
  const qc = useQueryClient()
  const { data: notes = [] } = useQuery({ queryKey: ['notes', caseId], queryFn: () => api.notes(caseId) })
  const [body, setBody] = useState('')
  const [author, setAuthor] = useState(() => localStorage.getItem('sentinel.author') ?? 'Investigator')
  const add = useMutation({
    mutationFn: () => { localStorage.setItem('sentinel.author', author); return api.addNote(caseId, body, author) },
    onSuccess: () => { setBody(''); qc.invalidateQueries({ queryKey: ['notes', caseId] }); qc.invalidateQueries({ queryKey: ['audit', caseId] }) },
  })
  return (
    <Panel>
      <PanelHead title="Investigator notes" sub="Written by people, kept separate from system-generated findings, and included in the report." />
      <ul className="divide-y divide-rule-2">
        {notes.map(n => (
          <li key={n.id} className="px-4 py-3">
            <p className="text-[12px] text-muted"><span className="font-medium text-ink-2">{n.author}</span> · {dateTime(n.created_at)} · human note</p>
            <p className="mt-1 whitespace-pre-wrap text-[13.5px]">{n.body}</p>
          </li>
        ))}
        {!notes.length && <li className="px-4 py-4 text-[13px] text-muted">No notes yet.</li>}
      </ul>
      <form className="space-y-2 border-t border-rule px-4 py-3" onSubmit={e => { e.preventDefault(); add.mutate() }}>
        <textarea className={inputCls + ' min-h-[80px]'} value={body} onChange={e => setBody(e.target.value)}
          placeholder="For example: Customer contacted support at 10:48 PM. Additional authentication logs requested." />
        {add.isError && <ErrorNote>{(add.error as Error).message}</ErrorNote>}
        <div className="flex items-center gap-2">
          <input aria-label="Your name" className={inputCls + ' max-w-[200px] py-1 text-[13px]'} value={author} onChange={e => setAuthor(e.target.value)} />
          <Button type="submit" variant="primary" size="sm" disabled={!body.trim() || add.isPending}>Add note</Button>
        </div>
      </form>
    </Panel>
  )
}

export function AuditView({ caseId }: { caseId: string }) {
  const { data = [] } = useQuery({ queryKey: ['audit', caseId], queryFn: () => api.audit(caseId), refetchInterval: 10_000 })
  return (
    <Panel>
      <PanelHead title="Audit trail" sub="Every upload, processing step, analysis run, note and report — append-only." />
      <table className="w-full text-[13px]">
        <tbody>
          {data.map((a, i) => (
            <tr key={i} className="border-b border-rule-2 last:border-0">
              <td className="tabular whitespace-nowrap px-4 py-1.5 text-muted">{dateTime(a.at)}</td>
              <td className="px-2 py-1.5">{humanize(a.action)}{a.evidence && <span className="ml-1.5 font-mono text-[12px] text-accent-ink">{a.evidence}</span>}</td>
              <td className="px-2 py-1.5 text-muted">{a.result !== 'OK' ? a.result : ''}</td>
              <td className="px-4 py-1.5 text-right text-[12px] text-faint">{a.actor}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}
