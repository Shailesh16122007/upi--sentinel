import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { ExhibitTag, Sources, useSources } from '@/components/evidence'
import { Badge, Panel, PanelHead } from '@/components/ui'
import { api } from '@/lib/api'
import { cn, dateTime, humanize, inr, shortDate } from '@/lib/format'
import type { CaseFull, FieldValue, Finding } from '@/lib/types'

export function Overview({ c, findings, goTo }: { c: CaseFull; findings: Finding[]; goTo: (tab: string) => void }) {
  const a = c.analysis!
  const d = c.disputed
  const conflicts = findings.filter(f => f.is_conflict)
  return (
    <div className="space-y-5">
      <KeyFacts c={c} goTo={goTo} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Panel>
            <PanelHead title="Disputed transaction"
              sub={d ? (d.match_basis ? `Matched across sources: ${d.match_basis}` : 'Found in a single source') : undefined} />
            {d ? <FieldTable c={c} conflicts={conflicts} /> : <p className="px-4 py-4 text-[13px] text-muted">No transaction could be identified from the submitted evidence. Add a payment screenshot, bank SMS or statement.</p>}
          </Panel>
          <Panel>
            <PanelHead title="Investigation summary" sub={`System-generated · ${a.summary_engine}. Every sentence links to the evidence it relies on.`} />
            <ul className="space-y-2 px-4 py-3 text-[13.5px] leading-relaxed">
              {a.summary.map((s, i) => (
                <li key={i} className="flex gap-2">
                  <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-faint" />
                  <span>{s.text} <CodeTags codes={s.sources} /></span>
                </li>
              ))}
            </ul>
          </Panel>
          {conflicts.length > 0 && (
            <Panel className="border-contra/30">
              <PanelHead title={`Evidence conflicts (${conflicts.length})`} sub="The system does not decide which evidence is correct. Both sides are preserved for review."
                aside={<button className="text-[12.5px] text-accent hover:underline" onClick={() => goTo('findings')}>All findings</button>} />
              <ul className="divide-y divide-rule-2">
                {conflicts.map(f => (
                  <li key={f.id} className="px-4 py-2.5 text-[13px]">
                    <div className="flex items-center gap-2 font-medium">{f.title}<Sources sources={f.sources} /></div>
                    <p className="mt-0.5 text-muted">{f.detail}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
        <div className="space-y-5">
          <Completeness c={c} />
          <HistoryPanel c={c} />
        </div>
      </div>
    </div>
  )
}

function KeyFacts({ c, goTo }: { c: CaseFull; goTo: (t: string) => void }) {
  const a = c.analysis!
  const d = c.disputed
  const items: [string, string, string | null, string?][] = [
    ['Disputed amount', inr(d?.amount ?? null), null],
    ['Transaction time', d?.occurred_at ? dateTime(d.occurred_at) : 'Not in evidence', d && d.time_precision !== 'EXACT' && d.occurred_at ? 'approximate' : null],
    ['Evidence completeness', `${a.completeness.score}%`, null, 'overview-completeness'],
    ['Evidence items', String(a.counts.evidence), null, 'sources'],
    ['Observed anomalies', String(a.counts.anomalies), null, 'findings'],
    ['Evidence conflicts', String(a.counts.conflicts), null, 'findings'],
    ['Missing evidence', String(a.counts.missing), null, 'findings'],
  ]
  return (
    <dl className="grid grid-cols-2 border-y border-rule bg-surface sm:grid-cols-4 xl:grid-cols-7">
      {items.map(([k, v, note, tab]) => (
        <div key={k} className="border-r border-rule-2 px-4 py-3 last:border-r-0">
          <dt className="text-[12px] text-muted">{k}</dt>
          <dd className="tabular mt-0.5 text-[17px] font-semibold leading-tight">
            {tab && tab !== 'overview-completeness' ? <button className="hover:text-accent" onClick={() => goTo(tab)}>{v}</button> : v}
            {note && <span className="ml-1 text-[11.5px] font-normal text-missing">{note}</span>}
          </dd>
        </div>
      ))}
    </dl>
  )
}

const FIELDS: [string, string, (v: any) => string][] = [
  ['amount', 'Amount', v => inr(Number(v), 2)],
  ['time', 'Date & time', v => dateTime(String(v))],
  ['reference', 'Reference / UTR', v => String(v)],
  ['beneficiary_vpa', 'Beneficiary UPI ID', v => String(v)],
  ['beneficiary_name', 'Beneficiary name', v => String(v)],
  ['status', 'Status', v => humanize(String(v))],
  ['channel', 'Channel', v => String(v)],
  ['account', 'Account', v => String(v)],
  ['bank', 'Bank', v => String(v)],
]

function FieldTable({ c, conflicts }: { c: CaseFull; conflicts: Finding[] }) {
  const d = c.disputed!
  const conflictFields = new Set(conflicts.map(f => f.data?.field).filter(Boolean))
  return (
    <table className="w-full text-[13px]">
      <tbody>
        {FIELDS.map(([key, label, fmt]) => {
          const vals: FieldValue[] = d.fields[key] ?? []
          const groups = new Map<string, FieldValue[]>()
          vals.forEach(v => { const k = fmt(v.value); groups.set(k, [...(groups.get(k) ?? []), v]) })
          const conflict = conflictFields.has(key)
          return (
            <tr key={key} className={cn('border-b border-rule-2 align-top last:border-0', conflict && 'bg-contra-tint')}>
              <th scope="row" className="w-[160px] px-4 py-2 text-left font-normal text-muted">{label}</th>
              <td className="px-2 py-2">
                {groups.size === 0 ? <span className="text-faint">Not available in submitted evidence</span> : (
                  <div className="space-y-1">
                    {[...groups.entries()].map(([val, vs]) => (
                      <div key={val} className="flex flex-wrap items-center gap-2">
                        <span className={cn(['reference', 'beneficiary_vpa', 'account'].includes(key) && 'font-mono text-[12.5px]', 'tabular')}>{val}</span>
                        <Sources sources={vs.map(v => ({ evidence_id: v.evidence_id, entity_id: v.entity_id }))} />
                        {key === 'time' && vs[0].precision && vs[0].precision !== 'EXACT' && <span className="text-[11.5px] text-missing">approximate ({humanize(vs[0].precision)})</span>}
                      </div>
                    ))}
                  </div>
                )}
              </td>
              <td className="w-[140px] whitespace-nowrap px-4 py-2 text-right">
                {conflict ? <Badge tone="bad">Conflict</Badge> : groups.size > 1 ? <Badge tone="outline">Several values</Badge>
                  : new Set(vals.map(v => v.evidence_id)).size > 1 ? <Badge tone="ok">Agrees</Badge> : null}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export function CodeTags({ codes }: { codes: string[] }) {
  const { evidence } = useSources()
  const map = new Map(evidence.map(e => [e.code, e]))
  return <span className="inline-flex flex-wrap gap-1 align-middle">{codes.map(code => {
    const e = map.get(code)
    return e ? <ExhibitTag key={code} source={{ evidence_id: e.id }} /> : null
  })}</span>
}

function Completeness({ c }: { c: CaseFull }) {
  const comp = c.analysis!.completeness
  return (
    <Panel>
      <PanelHead title={`Evidence completeness: ${comp.score}%`} sub={`${comp.earned} of ${comp.total} weighted points`} />
      <div className="px-4 pt-3">
        <div className="flex h-1.5 overflow-hidden rounded-full bg-rule-2" role="img" aria-label={`${comp.score}% complete`}>
          <div className="bg-accent" style={{ width: `${comp.score}%` }} />
        </div>
      </div>
      <ul className="px-4 py-2 text-[13px]">
        {comp.items.map(i => (
          <li key={i.key} className="grid grid-cols-[18px_1fr_auto] items-start gap-2 py-1">
            <span className={cn('mt-0.5 text-center font-semibold', i.status === 'present' ? 'text-ok' : i.status === 'partial' ? 'text-missing' : 'text-faint')}>
              {i.status === 'present' ? '✓' : i.status === 'partial' ? '½' : '✗'}
            </span>
            <span>
              <span className={i.status === 'missing' ? 'text-muted' : 'text-ink'}>{i.label}</span>
              {i.basis && <span className="block text-[12px] text-muted">{i.basis}</span>}
            </span>
            <span className="tabular text-[12px] text-muted">{i.earned}/{i.weight}</span>
          </li>
        ))}
      </ul>
      <p className="border-t border-rule-2 px-4 py-2 text-[12px] text-muted">{comp.method}</p>
    </Panel>
  )
}

function HistoryPanel({ c }: { c: CaseFull }) {
  const ml = c.analysis!.ml
  const { data = [] } = useQuery({ queryKey: ['history', c.id, c.analyzed_at], queryFn: () => api.history(c.id) })
  const d = c.disputed
  const hist = data.filter(h => h.occurred_at).map(h => ({ x: new Date(h.occurred_at!).getTime(), y: h.amount, who: h.beneficiary }))
  const disp = d?.occurred_at && d.amount ? [{ x: new Date(d.occurred_at).getTime(), y: d.amount, who: d.beneficiary_vpa ?? d.beneficiary }] : []
  return (
    <Panel>
      <PanelHead title="Compared with the customer’s history"
        sub={data.length ? `${data.length} historical transactions supplied` : 'No transaction history supplied'} />
      {hist.length > 0 && (
        <div className="h-[200px] px-2 pt-2" role="img" aria-label="Historical payment amounts over time with the disputed payment highlighted">
          <ResponsiveContainer>
            <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid stroke="#eceff3" />
              <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']} tickFormatter={v => shortDate(new Date(v).toISOString()).slice(0, 6)}
                tick={{ fontSize: 11, fill: '#5a6578' }} stroke="#dfe3ea" />
              <YAxis dataKey="y" type="number" scale="log" domain={['auto', 'auto']} ticks={[100, 1000, 10000, 100000]} allowDataOverflow={false}
                tickFormatter={v => `₹${v >= 1000 ? `${v / 1000}k` : v}`}
                tick={{ fontSize: 11, fill: '#5a6578' }} stroke="#dfe3ea" width={48} />
              <ZAxis range={[28, 28]} />
              <Tooltip cursor={false} content={({ payload }) => payload?.[0] ? (
                <div className="rounded-[var(--radius-sm)] border border-rule bg-surface px-2 py-1 text-[12px] shadow-sm">
                  {inr(payload[0].payload.y)} · {payload[0].payload.who ?? '—'}<br />{dateTime(new Date(payload[0].payload.x).toISOString())}
                </div>) : null} />
              <Scatter name="History" data={hist} fill="#8a93a3" />
              {disp.length > 0 && <Scatter name="Disputed" data={disp} fill="#b42318" shape="diamond" />}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="px-4 py-3 text-[13px]">
        {hist.length > 0 && <p className="mb-2 flex gap-3 text-[12px] text-muted">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-faint" />Past payments</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rotate-45 bg-contra" />Disputed payment</span>
          <span>log scale</span></p>}
        <h4 className="font-medium">Statistical check</h4>
        {ml.available ? (
          <p className="mt-0.5 text-muted">
            Isolation Forest trained on {ml.history_rows} past transactions rates this payment more unusual than
            {' '}<span className="font-medium text-ink">{ml.more_anomalous_than_pct}%</span> of them
            {ml.is_outlier ? ' and flags it as an outlier' : ''}. Largest deviations: {ml.top_deviations.map((x: any) => `${x.feature} (z ${x.z})`).join(', ')}.
            <span className="mt-1 block text-[12px]">{ml.note}</span>
          </p>
        ) : <p className="mt-0.5 text-muted">ML analysis unavailable. Reason: {ml.reason}</p>}
      </div>
    </Panel>
  )
}
