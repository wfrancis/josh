import { useState } from 'react'
import { DollarSign, Droplets, Layers, HardHat, BookOpen, Upload } from 'lucide-react'
import SundryRatesTab from './SundryRatesTab'
import ByMaterialTab from './ByMaterialTab'
import LaborCatalogTab from './LaborCatalogTab'
import BusinessRulesTab from './BusinessRulesTab'
import BulkImportTab from './BulkImportTab'

const TABS = [
  { id: 'sundry-rates', label: 'Sundries', icon: Droplets, component: SundryRatesTab },
  { id: 'by-material', label: 'By Material', icon: Layers, component: ByMaterialTab },
  { id: 'labor-catalog', label: 'Labor', icon: HardHat, component: LaborCatalogTab },
  { id: 'business-rules', label: 'Rules', icon: BookOpen, component: BusinessRulesTab },
  { id: 'bulk-import', label: 'Import', icon: Upload, component: BulkImportTab },
]

export default function PricingRulesPage() {
  const [activeTab, setActiveTab] = useState('sundry-rates')

  const ActiveComponent = TABS.find((t) => t.id === activeTab)?.component

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-10">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-extrabold text-white tracking-tight flex items-center gap-3">
          <DollarSign className="w-6 h-6 text-gray-400" />
          Pricing &amp; Rules
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Sundry rates, material rules, labor catalog, and business rules
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 sticky top-0 z-10 bg-[#0a0f1e] pb-px border-b border-white/[0.08]">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2.5 rounded-t-lg text-xs font-medium flex items-center gap-1.5 whitespace-nowrap transition-colors ${
                isActive
                  ? 'bg-white/[0.08] text-white border-b-2 border-orange-500'
                  : 'text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]'
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Active tab content */}
      <div className="mt-6">
        {ActiveComponent && <ActiveComponent />}
      </div>
    </div>
  )
}
