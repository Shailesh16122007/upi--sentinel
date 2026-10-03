import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { CaseTable } from '@/components/CaseTable'
import { Button, Empty, ErrorNote, Panel, PanelHead } from '@/components/ui'
import { api } from '@/lib/api'

export default function CaseList() {
  const nav = useNavigate()
  const real = useQuery({ queryKey: ['cases', 'real'], queryFn: () => api.cases(false), refetchInterval: 5000 })
  const demo = useQuery({ queryKey: ['cases', 'demo'], queryFn: () => api.cases(true) })
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <h1 className="text-[22px] font-semibold">Disputes</h1>
        <Button variant="primary" onClick={() => nav('/cases/new')}>Start a new dispute</Button>
      </div>
      {real.isError && <ErrorNote>{(real.error as Error).message}</ErrorNote>}
      <Panel>
        <PanelHead title="Cases" />
        {real.data?.length ? <CaseTable cases={real.data} /> : <Empty>No disputes yet. Start one and upload whatever evidence you have.</Empty>}
      </Panel>
      {!!demo.data?.length && (
        <Panel className="border-contra/25">
          <PanelHead title="Synthetic demonstration cases" sub="Generated demo data. Not real disputes; kept separate from the list above." />
          <CaseTable cases={demo.data} />
        </Panel>
      )}
    </div>
  )
}
