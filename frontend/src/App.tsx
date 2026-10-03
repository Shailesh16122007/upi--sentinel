import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { homeFor, useAuth } from './lib/auth'
import Login from './pages/Login'
import Notifications from './pages/Notifications'
import StaffDashboard from './pages/staff/Dashboard'
import { AuditAll, RelatedCases, Reports, Requests } from './pages/staff/Lists'
import Network from './pages/staff/Network'
import Queue from './pages/staff/Queue'
import Workspace from './pages/staff/Workspace'
import VictimDashboard from './pages/victim/Dashboard'
import MyCases from './pages/victim/MyCases'
import NewCase from './pages/victim/NewCase'
import Profile from './pages/victim/Profile'
import UploadPick from './pages/victim/UploadPick'
import VictimCase from './pages/victim/VictimCase'

const NotFound = () => <p className="py-10 text-muted">Page not found.</p>

export default function App() {
  const { account, ready } = useAuth()
  if (!ready) return null
  if (!account) {
    return <Routes><Route path="*" element={<Login />} /></Routes>
  }
  const home = homeFor(account.role)
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate replace to={home} />} />
        {account.role === 'VICTIM' && <>
          <Route path="/my" element={<VictimDashboard />} />
          <Route path="/my/cases" element={<MyCases />} />
          <Route path="/my/cases/new" element={<NewCase />} />
          <Route path="/my/cases/:id" element={<VictimCase />} />
          <Route path="/my/upload" element={<UploadPick />} />
          <Route path="/my/notifications" element={<Notifications />} />
          <Route path="/my/profile" element={<Profile />} />
        </>}
        {account.role === 'BANK' && <>
          <Route path="/bank" element={<StaffDashboard />} />
          <Route path="/bank/cases" element={<Queue />} />
          <Route path="/bank/cases/:id" element={<Workspace />} />
          <Route path="/bank/requests" element={<Requests />} />
          <Route path="/bank/related" element={<RelatedCases />} />
          <Route path="/bank/network" element={<Network />} />
          <Route path="/bank/reports" element={<Reports />} />
          <Route path="/bank/audit" element={<AuditAll />} />
          <Route path="/bank/notifications" element={<Notifications />} />
        </>}
        {account.role === 'CYBER' && <>
          <Route path="/cyber" element={<StaffDashboard />} />
          <Route path="/cyber/cases" element={<Queue />} />
          <Route path="/cyber/escalated" element={<Queue preset="ESCALATED" title="Escalated — awaiting acceptance" />} />
          <Route path="/cyber/closed" element={<Queue preset="done" title="Closed and resolved cases" />} />
          <Route path="/cyber/cases/:id" element={<Workspace />} />
          <Route path="/cyber/related" element={<RelatedCases />} />
          <Route path="/cyber/network" element={<Network />} />
          <Route path="/cyber/reports" element={<Reports />} />
          <Route path="/cyber/audit" element={<AuditAll />} />
          <Route path="/cyber/notifications" element={<Notifications />} />
        </>}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}
