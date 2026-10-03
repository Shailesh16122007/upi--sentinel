import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import { ExhibitTag } from '@/components/evidence'
import { Panel } from '@/components/ui'
import { cn, humanize } from '@/lib/format'
import type { Graph, GraphNode } from '@/lib/types'

const COLUMN: Record<string, number> = {
  EVIDENCE: 0, COMMUNICATION: 1, SESSION: 1, ACCOUNT_EVENT: 1, DEVICE: 1, AUTH_EVENT: 1, HISTORY: 1,
  CUSTOMER: 2, TRANSACTION: 2, BENEFICIARY: 3,
}
const KIND_LABEL: Record<string, string> = {
  EVIDENCE: 'Evidence item', COMMUNICATION: 'Communication', SESSION: 'Session', ACCOUNT_EVENT: 'Account change', DEVICE: 'Device',
  AUTH_EVENT: 'Authentication', HISTORY: 'History', CUSTOMER: 'Customer', TRANSACTION: 'Transaction', BENEFICIARY: 'Beneficiary',
}
const COL_X = [0, 290, 600, 880]

type Data = { node: GraphNode; selected: boolean }

function GNode({ data }: NodeProps<Node<Data>>) {
  const n = data.node
  const disputed = n.kind === 'TRANSACTION' && n.label.includes('disputed')
  return (
    <div className={cn('w-[220px] rounded-[var(--radius-sm)] border bg-surface px-2.5 py-1.5 text-left',
      data.selected ? 'border-accent ring-2 ring-accent/25' : disputed ? 'border-contra' : n.kind === 'EVIDENCE' ? 'border-accent/40' : 'border-rule')}>
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-faint" />
      <div className="text-[10.5px] text-muted">{KIND_LABEL[n.kind] ?? humanize(n.kind)}</div>
      <div className={cn('truncate text-[12.5px] font-medium', disputed && 'text-contra', n.kind === 'EVIDENCE' && 'font-mono text-[12px] text-accent-ink')}>{n.label}</div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-faint" />
    </div>
  )
}
const nodeTypes = { g: GNode }

export function GraphView({ graph }: { graph: Graph }) {
  const [sel, setSel] = useState<string | null>(() => graph.nodes.find(n => n.kind === 'TRANSACTION')?.id ?? null)
  const { nodes, edges } = useMemo(() => {
    const cols: GraphNode[][] = [[], [], [], []]
    graph.nodes.forEach(n => cols[COLUMN[n.kind] ?? 1].push(n))
    cols[2].sort((a, b) => (a.kind === 'CUSTOMER' ? -1 : b.kind === 'CUSTOMER' ? 1 : 0))
    const order = ['HISTORY', 'COMMUNICATION', 'SESSION', 'DEVICE', 'ACCOUNT_EVENT', 'AUTH_EVENT']
    cols[1].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || a.label.localeCompare(b.label))
    const tallest = Math.max(...cols.map(c => c.length))
    const nodes: Node<Data>[] = cols.flatMap((col, ci) => col.map((n, i) => ({
      id: n.id, type: 'g', data: { node: n, selected: n.id === sel },
      position: { x: COL_X[ci], y: i * 64 + ((tallest - col.length) * 64) / 2 },
    })))
    const edges: Edge[] = graph.edges.map((e, i) => {
      const hot = e.rel === 'CONFLICTS_WITH'
      const linked = sel && (e.source === sel || e.target === sel)
      return {
        id: `e${i}`, source: e.source, target: e.target, label: linked ? humanize(e.rel) : undefined,
        style: { stroke: hot ? '#b42318' : linked ? '#1f5fad' : '#c3cad5', strokeWidth: linked ? 1.6 : 1, strokeDasharray: hot ? '4 3' : undefined },
        labelStyle: { fontSize: 10.5, fill: '#2c3b55' }, labelBgStyle: { fill: '#ffffff' },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: linked ? '#1f5fad' : '#c3cad5' },
      }
    })
    return { nodes, edges }
  }, [graph, sel])
  const node = graph.nodes.find(n => n.id === sel)
  const related = node ? graph.edges.filter(e => e.source === node.id || e.target === node.id) : []
  const label = (id: string) => graph.nodes.find(n => n.id === id)?.label ?? id

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <Panel className="h-[620px] overflow-hidden">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.3} nodesDraggable nodesConnectable={false}
          onNodeClick={(_, n) => setSel(n.id)} proOptions={{ hideAttribution: true }}>
          <Background gap={24} size={1} color="#eceff3" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </Panel>
      <Panel className="h-fit">
        {!node ? <p className="p-4 text-[13px] text-muted">Select a node to see what it represents and where it came from.</p> : (
          <div className="space-y-4 p-4 text-[13px]">
            <div>
              <p className="text-[12px] text-muted">{KIND_LABEL[node.kind] ?? humanize(node.kind)}</p>
              <h3 className="text-[15px] font-semibold">{node.label}</h3>
            </div>
            {Object.keys(node.details).length > 0 && (
              <dl className="grid grid-cols-[110px_1fr] gap-x-2 gap-y-1">
                {Object.entries(node.details).map(([k, v]) => (
                  <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="break-words">{String(v)}</dd></div>
                ))}
              </dl>
            )}
            <div>
              <h4 className="mb-1 text-[12.5px] font-semibold text-muted">Evidence source</h4>
              {node.sources.length ? <ul className="space-y-1">{node.sources.map(s => (
                <li key={s.evidence_id} className="flex items-center gap-2"><ExhibitTag source={s} /><span className="truncate">{s.name}</span></li>
              ))}</ul> : <p className="text-muted">Derived from the case itself.</p>}
            </div>
            {related.length > 0 && (
              <div>
                <h4 className="mb-1 text-[12.5px] font-semibold text-muted">Relationships</h4>
                <ul className="space-y-1">{related.map((e, i) => (
                  <li key={i}><span className="text-muted">{humanize(e.rel)}:</span> {e.source === node.id ? label(e.target) : label(e.source)}
                    {e.basis && <span className="block text-[12px] text-muted">{e.basis}</span>}</li>
                ))}</ul>
              </div>
            )}
            {node.events.length > 0 && (
              <div>
                <h4 className="mb-1 text-[12.5px] font-semibold text-muted">Related events</h4>
                <ul className="space-y-1.5">{node.events.map((e, i) => (
                  <li key={i}><span className="text-[12px] text-muted">{e.time}</span><br />{e.description}</li>
                ))}</ul>
              </div>
            )}
          </div>
        )}
      </Panel>
    </div>
  )
}
