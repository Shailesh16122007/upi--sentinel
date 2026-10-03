import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { CaseHeader } from '@/components/CaseHeader'
import { SourceProvider } from '@/components/evidence'
import { FindingsView } from '@/components/investigation/Findings'
import { GraphView } from '@/components/investigation/GraphView'
import { Overview } from '@/components/investigation/Overview'
import { AuditView, NotesView, SourcesView } from '@/components/investigation/Records'
import { TimelineView } from '@/components/investigation/Timeline'
import { Button, ErrorNote, Panel, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { api } from '@/lib/api'

export default function CaseInvestigation() {
  const { id = '' } = useParams()
  return <SourceProvider caseId={id}><Investigation id={id} /></SourceProvider>
}

function Investigation({ id }: { id: string }) {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'overview'
  const goTo = (t: string) => setParams({ tab: t }, { replace: true })
  const { data: c, error } = useQuery({ queryKey: ['case', id], queryFn: () => api.case(id),
    refetchInterval: q => (q.state.data?.processing ? 2000 : false) })
  const key = c?.analyzed_at ?? 'none'
  const findings = useQuery({ queryKey: ['findings', id, key], queryFn: () => api.findings(id), enabled: !!c?.analyzed_at })
  const timeline = useQuery({ queryKey: ['timeline', id, key], queryFn: () => api.timeline(id), enabled: !!c?.analyzed_at })
  const graph = useQuery({ queryKey: ['graph', id, key], queryFn: () => api.graph(id), enabled: !!c?.analyzed_at && tab === 'graph' })
  const rerun = useMutation({ mutationFn: () => api.analyze(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['case', id] }) })

  const logged = useRef(false)
  useEffect(() => {
    if (!logged.current && id) { logged.current = true; api.opened(id).catch(() => {}) }
  }, [id])

  if (error) return <ErrorNote>{(error as Error).message}</ErrorNote>
  if (!c) return null
  if (!c.analyzed_at) {
    return (
      <>
        <CaseHeader c={c} />
        <Panel className="p-6 text-[14px]">
          <p>{c.processing ? 'Evidence is still being processed. The investigation opens automatically when it is ready.' : 'No evidence has been analysed for this case yet.'}</p>
          <Link to={`/cases/${id}/evidence`} className="mt-3 inline-block text-accent underline">Go to evidence upload</Link>
        </Panel>
      </>
    )
  }
  const f = findings.data ?? []
  const counts = c.analysis!.counts
  return (
    <>
      <CaseHeader c={c} />
      <Tabs value={tab} onValueChange={goTo}>
        <div className="flex items-end justify-between gap-3">
          <TabsList className="flex-1">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="timeline">Timeline</TabsTrigger>
            <TabsTrigger value="graph">Evidence graph</TabsTrigger>
            <TabsTrigger value="findings">Findings <span className="text-faint">{counts.supporting + counts.contradictory + counts.contextual + counts.missing}</span></TabsTrigger>
            <TabsTrigger value="sources">Evidence sources <span className="text-faint">{counts.evidence}</span></TabsTrigger>
            <TabsTrigger value="notes">Investigator notes</TabsTrigger>
            <TabsTrigger value="audit">Audit trail</TabsTrigger>
          </TabsList>
          <div className="mb-1 hidden gap-2 md:flex">
            <Button size="sm" onClick={() => rerun.mutate()} disabled={rerun.isPending}>{rerun.isPending ? 'Re-running…' : 'Re-run analysis'}</Button>
            <Link to={`/cases/${id}/report`}><Button size="sm" variant="primary">Generate report</Button></Link>
          </div>
        </div>
        {rerun.isError && <div className="mt-3"><ErrorNote>{(rerun.error as Error).message}</ErrorNote></div>}
        <div className="pt-5">
          <TabsContent value="overview"><Overview c={c} findings={f} goTo={goTo} /></TabsContent>
          <TabsContent value="timeline">{timeline.data && <TimelineView events={timeline.data} />}</TabsContent>
          <TabsContent value="graph">{graph.data ? <GraphView graph={graph.data} /> : <p className="text-muted">Building graph…</p>}</TabsContent>
          <TabsContent value="findings"><FindingsView findings={f} /></TabsContent>
          <TabsContent value="sources"><SourcesView caseId={id} /></TabsContent>
          <TabsContent value="notes"><NotesView caseId={id} /></TabsContent>
          <TabsContent value="audit"><AuditView caseId={id} /></TabsContent>
        </div>
      </Tabs>
    </>
  )
}
