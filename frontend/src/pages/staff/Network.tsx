import { useQuery } from '@tanstack/react-query'
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Badge, Empty, Panel, PanelHead, PageHead, StatusBadge } from '@/components/ui'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { cn, dateTime, inr, lakh } from '@/lib/format'
import type { Cluster, NetGraph } from '@/lib/types'

type D = { n: NetGraph['nodes'][number]; selected: boolean }

function NetNode({ data }: NodeProps<Node<D>>) {
  const n = data.n
  const id = n.kind === 'IDENTIFIER'
  return (
    <div className={cn('rounded-[var(--radius-sm)] border bg-surface px-2.5 py-1.5 text-center',
      id ? 'w-[230px] border-contra/60' : 'w-[190px] border-rule', data.selected && 'ring-2 ring-accent/30')}>
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-faint" />
      {id ? <>
        <div className="text-[10.5px] text-muted">{n.type_label}</div>
        <div className="truncate font-mono text-[12.5px] font-semibold text-contra">{n.label}</div>
        <div className="text-[11px] text-muted">{n.case_count} cases · {lakh(n.total_amount)}</div>
      </> : <>
        <div className="truncate text-[11px] text-muted">{n.victim}</div>
        <div className="font-mono text-[12px] font-medium">{n.label}</div>
        <div className="tabular text-[12px]">{inr(n.amount)}</div>
      </>}
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-faint" />
    </div>
  )
}
const nodeTypes = { n: NetNode }

function layout(g: NetGraph, sel: string | null) {
  const ids = g.nodes.filter(n => n.kind === 'IDENTIFIER')
  const nodes: Node<D>[] = []
  const placed = new Set<string>()
  let y = 0
  ids.forEach(idn => {
    const cases = g.edges.filter(e => e.target === idn.id).map(e => g.nodes.find(n => n.id === e.source)!).filter(Boolean)
    const width = Math.max(cases.length, 1) * 215
    const top = cases.slice(0, Math.ceil(cases.length / 2))
    const bottom = cases.slice(Math.ceil(cases.length / 2))
    const row = (list: typeof cases, yy: number) => list.forEach((c, i) => {
      if (placed.has(c.id)) return
      placed.add(c.id)
      nodes.push({ id: c.id, type: 'n', position: { x: (width - list.length * 215) / 2 + i * 215, y: yy }, data: { n: c, selected: c.id === sel } })
    })
    row(top, y)
    nodes.push({ id: idn.id, type: 'n', position: { x: width / 2 - 115, y: y + 130 }, data: { n: idn, selected: idn.id === sel } })
    row(bottom, y + 260)
    y += bottom.length ? 420 : 260
  })
  const edges: Edge[] = g.edges.map((e, i) => ({
    id: `e${i}`, source: e.source, target: e.target, label: e.amount ? inr(e.amount) : 'amount unknown',
    style: { stroke: '#b42318', strokeWidth: 1.2 }, labelStyle: { fontSize: 11, fill: '#13233f' }, labelBgStyle: { fill: '#ffffff' },
  }))
  return { nodes, edges }
}

export default function Network() {
  const me = useMe()
  const nav = useNavigate()
  const base = me.role === 'BANK' ? '/bank' : '/cyber'
  const [p, setP] = useSearchParams()
  const synthetic = p.get('synthetic') === '1'
  const clusterId = p.get('cluster') ?? undefined
  const { data: clusters = [] } = useQuery({ queryKey: ['clusters', synthetic], queryFn: () => api.clusters(synthetic) })
  const { data: g } = useQuery({ queryKey: ['network', synthetic, clusterId], queryFn: () => api.network(synthetic, clusterId) })
  const [sel, setSel] = useState<string | null>(null)
  const flow = useMemo(() => (g ? layout(g, sel) : { nodes: [], edges: [] }), [g, sel])
  const node = g?.nodes.find(n => n.id === sel)
  const cluster: Cluster | undefined = node?.kind === 'IDENTIFIER' ? clusters.find(c => c.id === node.cluster_id)
    : clusterId ? clusters.find(c => c.id === clusterId) : undefined
  const set = (k: string, v?: string) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); setP(n, { replace: true }); setSel(null) }

  return (
    <div className="space-y-4">
      <PageHead title="Mule network" sub="Related transaction clusters: the same beneficiary or contact identifier in two or more submitted cases. Built from case records only."
        aside={<div className="flex gap-1 text-[12.5px]">
          {[['', 'Real cases'], ['1', 'Synthetic demo data']].map(([k, l]) => (
            <button key={k} onClick={() => set('synthetic', k || undefined)}
              className={cn('rounded-[var(--radius-sm)] border px-2.5 py-1', (synthetic ? '1' : '') === k ? 'border-accent bg-accent-tint text-accent-ink' : 'border-rule text-muted')}>{l}</button>))}
        </div>} />
      {synthetic && <div className="rounded-[var(--radius-sm)] bg-contra px-3 py-1.5 text-[12.5px] font-medium text-white">Showing synthetic demonstration data only. It is never combined with real cases.</div>}
      <Panel>
        <PanelHead title={`Clusters (${clusters.length})`} sub={me.role === 'BANK' ? 'Clusters that include at least one of your bank’s cases. Other banks’ customers are not identified.' : undefined} />
        {!clusters.length ? <Empty>No related transaction cluster detected.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead><tr className="border-b border-rule text-left text-[12px] text-muted">
                {['Identifier', 'Type', 'Related cases', 'Total disputed amount', 'Time window', 'Last activity', ''].map(h => <th key={h} className="px-3 py-2 font-medium first:pl-4">{h}</th>)}
              </tr></thead>
              <tbody>
                {clusters.map(c => (
                  <tr key={c.id} className={cn('border-b border-rule-2', clusterId === c.id && 'bg-accent-tint')}>
                    <td className="px-3 py-2 pl-4 font-mono font-medium">{c.value}</td>
                    <td className="px-3 py-2 text-muted">{c.type_label}</td>
                    <td className="px-3 py-2"><button className="font-semibold text-accent hover:underline" onClick={() => set('cluster', c.id)}>{c.case_count}</button></td>
                    <td className="tabular px-3 py-2">{inr(c.total_amount)}{c.amount_known_cases < c.case_count && <span className="text-[12px] text-missing"> ({c.case_count - c.amount_known_cases} unknown)</span>}</td>
                    <td className="px-3 py-2">{c.window_hours != null ? `${c.window_hours} h` : '—'}</td>
                    <td className="px-3 py-2 text-muted">{dateTime(c.last_at)}</td>
                    <td className="px-3 py-2 text-right"><button className="text-accent hover:underline" onClick={() => set('cluster', c.id)}>Show graph</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {g && g.nodes.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
          <Panel className="h-[560px] overflow-hidden">
            <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} fitView minZoom={0.2} nodesConnectable={false}
              onNodeClick={(_, n) => setSel(n.id)} proOptions={{ hideAttribution: true }}>
              <Background gap={24} size={1} color="#eceff3" /><Controls showInteractive={false} />
            </ReactFlow>
          </Panel>
          <Panel className="h-fit">
            {!node && !cluster && <p className="p-4 text-[13px] text-muted">Select an identifier or a case to see the underlying cases.</p>}
            {node?.kind === 'CASE' && (
              <div className="space-y-2 p-4 text-[13px]">
                <p className="text-[12px] text-muted">Case</p><h3 className="font-mono text-[15px] font-semibold">{node.label}</h3>
                <p>{node.victim} · {node.bank}</p><p className="tabular">{inr(node.amount)} · {node.status_label}</p>
                {node.can_open ? <button className="text-accent hover:underline" onClick={() => nav(`${base}/cases/${node.case_id}`)}>Open case</button>
                  : <p className="text-[12px] text-faint">You do not have access to this case.</p>}
              </div>
            )}
            {(node?.kind === 'IDENTIFIER' || (!node && cluster)) && cluster && (
              <div className="space-y-3 p-4 text-[13px]">
                <div><p className="text-[12px] text-muted">{cluster.type_label}</p><h3 className="font-mono text-[15px] font-semibold">{cluster.value}</h3>
                  <p className="text-contra">{cluster.label}</p></div>
                <dl className="grid grid-cols-[130px_1fr] gap-y-1">
                  <dt className="text-muted">Related cases</dt><dd>{cluster.case_count}</dd>
                  <dt className="text-muted">Total disputed</dt><dd className="tabular">{inr(cluster.total_amount)}</dd>
                  <dt className="text-muted">Time window</dt><dd>{cluster.window_hours != null ? `${cluster.window_hours} hours` : '—'}</dd>
                </dl>
                <ul className="divide-y divide-rule-2 border-y border-rule-2">
                  {cluster.cases.map(c => (
                    <li key={c.id} className="py-1.5">
                      <div className="flex items-center gap-2"><span className="font-mono">{c.ref}</span><span className="tabular ml-auto">{inr(c.amount)}</span></div>
                      <div className="flex items-center gap-2 text-[12px] text-muted"><span className="truncate">{c.victim}</span><StatusBadge status={c.status} label={c.status_label} />
                        {c.relationship === 'BENEFICIARY' && <Badge tone="outline">recipient</Badge>}
                        {c.can_open && <button className="ml-auto text-accent hover:underline" onClick={() => nav(`${base}/cases/${c.id}`)}>Open</button>}</div>
                    </li>
                  ))}
                </ul>
                <p className="text-[12px] text-faint">Shared identifiers make these cases possibly related. This does not by itself establish an organised network.</p>
              </div>
            )}
          </Panel>
        </div>
      )}
    </div>
  )
}
