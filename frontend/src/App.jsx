import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import AllJobs from './components/AllJobs'
import JobDetail from './components/JobDetail'
import SettingsPage from './components/SettingsPage'
import InternalRatesPage from './components/InternalRatesPage'
import PricingRulesPage from './components/PricingRulesPage'
import VendorContactsPage from './components/VendorContactsPage'
import RulesRegistryPage from './components/RulesRegistryPage'
import MaterialQuotesHub from './components/MaterialQuotesHub'

function LegacyMaterialQuotesRedirect({ email = false }) {
  const location = useLocation()
  const destination = email ? '/jobs/bids/quote-emails' : '/jobs/bids'
  return <Navigate replace to={`${destination}${location.search}`} />
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/jobs" element={<AllJobs />} />
        <Route path="/jobs/bids" element={<MaterialQuotesHub />} />
        <Route path="/jobs/bids/quote-emails" element={<MaterialQuotesHub />} />
        <Route path="/jobs/:jobId" element={<JobDetail />} />
        <Route path="/material-quotes" element={<LegacyMaterialQuotesRedirect />} />
        <Route path="/material-quotes/email" element={<LegacyMaterialQuotesRedirect email />} />
        <Route path="/pricing-rules" element={<PricingRulesPage />} />
        <Route path="/rules" element={<RulesRegistryPage />} />
        <Route path="/internal-rates" element={<PricingRulesPage />} />
        <Route path="/vendor-contacts" element={<VendorContactsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Layout>
  )
}
