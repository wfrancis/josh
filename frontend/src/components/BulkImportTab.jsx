import { useState, useEffect } from 'react'
import { HardHat, ShoppingCart, FileSpreadsheet, Loader2 } from 'lucide-react'
import { api } from '../api'
import FileUpload from './FileUpload'

export default function BulkImportTab() {
  // Labor catalog
  const [laborLoading, setLaborLoading] = useState(false)
  const [laborSuccess, setLaborSuccess] = useState(false)
  const [laborError, setLaborError] = useState(null)
  const [laborCount, setLaborCount] = useState(null)
  const [laborFetching, setLaborFetching] = useState(true)

  // Price list
  const [priceLoading, setPriceLoading] = useState(false)
  const [priceSuccess, setPriceSuccess] = useState(false)
  const [priceError, setPriceError] = useState(null)
  const [priceCount, setPriceCount] = useState(null)
  const [priceFetching, setPriceFetching] = useState(true)

  // Load counts on mount
  useEffect(() => {
    api.getLaborCatalog()
      .then(data => setLaborCount(data?.count || 0))
      .catch(() => setLaborCount(0))
      .finally(() => setLaborFetching(false))

    api.getPriceList()
      .then(data => setPriceCount(data?.count || 0))
      .catch(() => setPriceCount(0))
      .finally(() => setPriceFetching(false))
  }, [])

  // Labor upload
  const handleLaborUpload = async (file) => {
    setLaborLoading(true)
    setLaborError(null)
    try {
      await api.uploadLaborCatalog(file)
      setLaborSuccess(true)
      const data = await api.getLaborCatalog()
      setLaborCount(data?.count || 0)
    } catch (err) {
      setLaborError(err.message)
    } finally {
      setLaborLoading(false)
    }
  }

  // Price list upload
  const handlePriceUpload = async (file) => {
    setPriceLoading(true)
    setPriceError(null)
    try {
      await api.uploadPriceList(file)
      setPriceSuccess(true)
      const data = await api.getPriceList()
      setPriceCount(data?.count || 0)
    } catch (err) {
      setPriceError(err.message)
    } finally {
      setPriceLoading(false)
    }
  }

  return (
    <div className="space-y-6">

      {/* Labor Catalog Upload */}
      <div className="glass-card p-8">
        <div className="flex items-start gap-4 mb-6">
          <div className="w-11 h-11 rounded-xl bg-violet-500/10 flex items-center justify-center flex-shrink-0">
            <HardHat className="w-5 h-5 text-violet-400" />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-white">Labor Catalog</h2>
            <p className="text-sm text-gray-500 mt-1">
              Upload a PDF or Excel file containing labor rates per material type. These rates are used when generating bids.
            </p>
          </div>
          {laborFetching ? (
            <Loader2 className="w-4 h-4 text-gray-500 animate-spin mt-1" />
          ) : laborCount > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400 whitespace-nowrap mt-1">
              {laborCount} entries loaded
            </span>
          )}
        </div>

        <FileUpload
          accept=".pdf,.xlsx,.xls"
          label="Upload Labor Catalog"
          description="PDF or Excel file with labor rates"
          icon={FileSpreadsheet}
          onUpload={handleLaborUpload}
          onReset={() => setLaborSuccess(false)}
          loading={laborLoading}
          success={laborSuccess}
          successMessage="Labor catalog uploaded successfully"
        />

        {laborError && (
          <div className="mt-3 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
            {laborError}
          </div>
        )}
      </div>

      {/* Price List Upload */}
      <div className="glass-card p-8">
        <div className="flex items-start gap-4 mb-6">
          <div className="w-11 h-11 rounded-xl bg-emerald-500/10 flex items-center justify-center flex-shrink-0">
            <ShoppingCart className="w-5 h-5 text-emerald-400" />
          </div>
          <div className="flex-1">
            <h2 className="text-lg font-bold text-white">Price List</h2>
            <p className="text-sm text-gray-500 mt-1">
              Upload a CSV or Excel file with material pricing. Used to match against vendor quotes and populate bid line items.
            </p>
          </div>
          {priceFetching ? (
            <Loader2 className="w-4 h-4 text-gray-500 animate-spin mt-1" />
          ) : priceCount > 0 && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 whitespace-nowrap mt-1">
              {priceCount} entries loaded
            </span>
          )}
        </div>

        <FileUpload
          accept=".csv,.xlsx,.xls"
          label="Upload Price List"
          description="CSV or Excel file with material pricing"
          icon={FileSpreadsheet}
          onUpload={handlePriceUpload}
          onReset={() => setPriceSuccess(false)}
          loading={priceLoading}
          success={priceSuccess}
          successMessage="Price list uploaded successfully"
        />

        {priceError && (
          <div className="mt-3 px-4 py-3 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
            {priceError}
          </div>
        )}
      </div>
    </div>
  )
}
