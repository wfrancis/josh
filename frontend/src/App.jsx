import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import AllJobs from './components/AllJobs'
import JobDetail from './components/JobDetail'
import SettingsPage from './components/SettingsPage'
import InternalRatesPage from './components/InternalRatesPage'
import PricingRulesPage from './components/PricingRulesPage'
import VendorContactsPage from './components/VendorContactsPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/jobs" element={<AllJobs />} />
        <Route path="/jobs/:jobId" element={<JobDetail />} />
        <Route path="/pricing-rules" element={<PricingRulesPage />} />
        <Route path="/internal-rates" element={<PricingRulesPage />} />
        <Route path="/vendor-contacts" element={<VendorContactsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Layout>
  )
}
