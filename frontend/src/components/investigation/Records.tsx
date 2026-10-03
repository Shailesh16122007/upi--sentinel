import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { EvidenceStatus, useSources } from '@/components/evidence'
import { Badge, Button, ErrorNote, inputCls, Panel, PanelHead, SyntheticBadge } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { bytes, dateTime, humanize, kindLabel, methodLabel } from '@/lib/format'

export function SourcesView() {
  const { evidence, open } = useSources()
  return (
    <Panel>
      <PanelHead title={`Evidence (${evidence.length})`}
        sub="Every file exactly as uploaded. Originals are stored unchanged with a SHA-256 fingerprint. Select a row to view the original and what was extracted." />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-[13px]">
          <thead><tr className="border-b border-rule text-left text-[12px] text-muted">
            {['Code', 'File', 'Type', 'Read with', 'Language', 'Items', 'Status', 'Uploaded', 'Integrity'].map(h => <th key={h} className="px-3 py-2 font-medium first:pl-4">{h}</th>)}
          </tr></thead>
          <tbody>
            {evidence.map(e => (
              <tr key={e.id} tabIndex={0} onClick={() => open({ evidenceId: e.id })} onKeyDown={k => k.key === 'Enter' && open({ evidenceId: e.id })}
                className="cursor-pointer border-b border-rule-2 align-top hover:bg-tint">
                <td className="px-3 py-2 pl-4 font-mono text-[12.5px] font-medium text-accent-ink">{e.code}</td>
                <td className="px-3 py-2">{e.original_name} {e.is_synthetic && <SyntheticBadge />}
                  <div className="text-[12px] text-muted">by {e.uploaded_by_role === 'VICTIM' ? 'customer' : humanize(e.uploaded_by_role ?? e.source)}</div></td>
                <td className="px-3 py-2">{kindLabel(e)}</td>
                <td className="px-3 py-2 text-muted">{methodLabel(e.method)}</td>
                <td className="px-3 py-2 text-muted">{e.language?.label ?? '—'}</td>
                <td className="tabular px-3 py-2">{e.entities.length}</td>
                <td className="px-3 py-2"><EvidenceStatus status={e.status} />
                  {e.image_check?.indicators.length ? <div className="mt-0.5"><Badge tone="warn">Possible manipulation indicators</Badge></div> : null}</td>
                <td className="whitespace-nowrap px-3 py-2 text-muted">{dateTime(e.uploaded_at)} · {bytes(e.size_bytes)}</td>
                <td className="px-3 py-2"><span className={e.integrity.result === 'MATCH' ? 'text-ok' : 'text-contra'}>{e.integrity.status}</span>
                  <div className="font-mono text-[11px] text-muted">{e.sha256?.slice(0, 8)}…{e.sha256?.slice(-4)}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

export function NotesView({ caseId }: { caseId: string }) {
  const me = useMe()
  const qc = useQueryClient()
  const { data: notes = [] } = useQuery({ queryKey: ['notes', caseId], queryFn: () => api.notes(caseId) })
  const [body, setBody] = useState('')
  const [shared, setShared] = useState(false)
  const add = useMutation({
    mutationFn: () => api.addNote(caseId, { body, visibility: me.role === 'CYBER' ? (shared ? 'BANK_AND_CYBER' : 'CYBER_ONLY') : undefined }),
    onSuccess: () => { setBody(''); qc.invalidateQueries({ queryKey: ['notes', caseId] }); qc.invalidateQueries({ queryKey: ['audit', caseId] }) },
  })
  return (
    <Panel>
      <PanelHead title="Investigation notes" sub="Written by people, kept separate from system findings, never shown to the customer, included in investigator reports." />
      <ul className="divide-y divide-rule-2">
        {notes.map(n => (
          <li key={n.id} className="px-4 py-3">
            <p className="flex flex-wrap items-center gap-2 text-[12px] text-muted"><span className="font-medium text-ink-2">{n.author}</span>
              <Badge tone="outline">{n.role === 'BANK' ? 'Bank' : 'Cyber crime'}</Badge>{dateTime(n.created_at)}
              {n.visibility === 'CYBER_ONLY' && <Badge tone="neutral">Cyber crime only</Badge>}
              {n.finding_title && <span>· on finding “{n.finding_title}” ({humanize(n.assessment)})</span>}</p>
            <p className="mt-1 whitespace-pre-wrap text-[13.5px]">{n.body}</p>
          </li>
        ))}
        {!notes.length && <li className="px-4 py-4 text-[13px] text-muted">No notes yet.</li>}
      </ul>
      <form className="space-y-2 border-t border-rule px-4 py-3" onSubmit={e => { e.preventDefault(); add.mutate() }}>
        <textarea className={inputCls + ' min-h-[80px]'} value={body} onChange={e => setBody(e.target.value)}
          placeholder="For example: Beneficiary appears in multiple related complaints. Further investigation required." />
        {add.isError && <ErrorNote>{(add.error as Error).message}</ErrorNote>}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" size="sm" disabled={!body.trim() || add.isPending}>Add note</Button>
          {me.role === 'CYBER' && <label className="flex items-center gap-1.5 text-[12.5px] text-muted">
            <input type="checkbox" checked={shared} onChange={e => setShared(e.target.checked)} />Share with the bank</label>}
          <span className="text-[12px] text-faint">Signed as {me.name}</span>
        </div>
      </form>
    </Panel>
  )
}

export function AuditView({ caseId }: { caseId: string }) {
  const { data = [] } = useQuery({ queryKey: ['audit', caseId], queryFn: () => api.audit(caseId), refetchInterval: 10_000 })
  return (
    <Panel>
      <PanelHead title="Audit trail" sub="Append-only record of every upload, extraction, analysis, view, status change, note and report. It cannot be edited." />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-[13px]">
          <tbody>
            {data.map((a, i) => (
              <tr key={i} className="border-b border-rule-2 last:border-0">
                <td className="tabular whitespace-nowrap px-4 py-1.5 text-muted">{dateTime(a.at)}</td>
                <td className="px-2 py-1.5">{a.label}{a.evidence && <span className="ml-1.5 font-mono text-[12px] text-accent-ink">{a.evidence}</span>}</td>
                <td className="px-2 py-1.5 text-muted">{a.result !== 'OK' ? a.result : ''}</td>
                <td className="whitespace-nowrap px-4 py-1.5 text-right text-[12px] text-faint">{a.actor}{a.role ? ` · ${a.role === 'VICTIM' ? 'Customer' : humanize(a.role)}` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
