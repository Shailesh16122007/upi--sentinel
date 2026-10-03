import { Navigate, Route, Routes, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AppShell } from './components/AppShell'
import { api } from './lib/api'
import CaseEvidence from './pages/CaseEvidence'
import CaseInvestigation from './pages/CaseInvestigation'
import CaseList from './pages/CaseList'
import CaseReport from './pages/CaseReport'
import Home from './pages/Home'
import NewCase from './pages/NewCase'

function CaseIndex() {
  const { id = '' } = useParams()
  const { data } = useQuery({ queryKey: ['case', id], queryFn: () => api.case(id) })
  if (!data) return null
  return <Navigate replace to={`/cases/${id}/${data.analyzed_at ? 'investigation' : 'evidence'}`} />
}

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/cases" element={<CaseList />} />
        <Route path="/cases/new" element={<NewCase />} />
        <Route path="/cases/:id" element={<CaseIndex />} />
        <Route path="/cases/:id/evidence" element={<CaseEvidence />} />
        <Route path="/cases/:id/investigation" element={<CaseInvestigation />} />
        <Route path="/cases/:id/report" element={<CaseReport />} />
        <Route path="*" element={<p className="py-10 text-muted">Page not found.</p>} />
      </Routes>
    </AppShell>
  )
}
