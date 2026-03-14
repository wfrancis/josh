import { useState, useRef, useCallback } from 'react'
import { Upload, FileSpreadsheet, FileText, X, CheckCircle2, Loader2 } from 'lucide-react'

export default function FileUpload({
  accept, multiple = false, onUpload, onReset,
  label = 'Upload File', description = 'Drag and drop or click to browse',
  icon: CustomIcon, loading = false, success = false,
  successMessage = 'File uploaded successfully',
}) {
  const [dragOver, setDragOver] = useState(false)
  const [files, setFiles] = useState([])
  const inputRef = useRef(null)

  const handleDrag = useCallback((e) => { e.preventDefault(); e.stopPropagation() }, [])
  const handleDragIn = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setDragOver(true) }, [])
  const handleDragOut = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setDragOver(false) }, [])
  const handleDrop = useCallback((e) => {
    e.preventDefault(); e.stopPropagation(); setDragOver(false)
    const droppedFiles = Array.from(e.dataTransfer.files)
    console.log('[FileUpload] drop:', droppedFiles.length, 'files, multiple:', multiple, droppedFiles.map(f => `${f.name} (${f.size}b)`))
    if (droppedFiles.length) { setFiles(droppedFiles); onUpload?.(multiple ? droppedFiles : droppedFiles[0]) }
  }, [onUpload, multiple])

  const handleChange = (e) => {
    const selected = Array.from(e.target.files)
    console.log('[FileUpload] change:', selected.length, 'files, multiple:', multiple, selected.map(f => `${f.name} (${f.size}b)`))
    if (selected.length) { setFiles(selected); onUpload?.(multiple ? selected : selected[0]) }
  }

  const Icon = CustomIcon || (accept?.includes('.xls') ? FileSpreadsheet : FileText)

  if (success) {
    return (
      <div className="upload-zone !border-emerald-500/30 !bg-emerald-500/[0.04] text-center">
        <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
        <p className="text-sm font-medium text-emerald-300">{successMessage}</p>
        <button
          onClick={() => { setFiles([]); inputRef.current && (inputRef.current.value = ''); onReset?.() }}
          className="mt-2 text-xs text-emerald-500 hover:text-emerald-400 underline"
        >Upload another</button>
      </div>
    )
  }

  return (
    <div>
      <div
        className={`upload-zone text-center ${dragOver ? 'drag-over' : ''}`}
        onDragEnter={handleDragIn} onDragLeave={handleDragOut}
        onDragOver={handleDrag} onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input ref={inputRef} type="file" accept={accept} multiple={multiple}
               onChange={handleChange} className="hidden" />
        {loading ? (
          <div className="flex flex-col items-center py-4">
            <div className="relative w-16 h-16 mx-auto mb-5">
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-si-bright/20 to-blue-500/20 animate-pulse" />
              <div className="relative w-full h-full rounded-2xl bg-white/[0.04] flex items-center justify-center border border-white/[0.08]"
                   style={{ animation: 'pulse-glow 2s ease-in-out infinite' }}>
                <svg className="w-8 h-8 text-si-bright" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
                </svg>
              </div>
            </div>
            <p className="text-sm font-medium text-white mb-1">AI is analyzing your files</p>
            <div className="flex items-center justify-center gap-1 mb-4">
              <span className="text-xs text-gray-500">Processing</span>
              <span className="flex gap-0.5 ml-1">
                <span className="ai-dot w-1 h-1 rounded-full bg-si-bright inline-block" />
                <span className="ai-dot w-1 h-1 rounded-full bg-si-bright inline-block" />
                <span className="ai-dot w-1 h-1 rounded-full bg-si-bright inline-block" />
              </span>
            </div>
            <div className="w-48 h-1 mx-auto rounded-full overflow-hidden bg-white/[0.06]">
              <div className="ai-thinking-bar h-full rounded-full" />
            </div>
          </div>
        ) : (
          <>
            <div className="w-14 h-14 rounded-2xl bg-si-bright/[0.08] flex items-center justify-center mx-auto mb-4
                          border border-si-bright/[0.1]">
              <Icon className="w-7 h-7 text-si-bright" />
            </div>
            <p className="text-sm font-semibold text-gray-200 mb-1">{label}</p>
            <p className="text-xs text-gray-500">{description}</p>
          </>
        )}
      </div>

      {files.length > 0 && !loading && (
        <div className="mt-3 space-y-2">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-2 px-3 py-2 bg-white/[0.03] border border-white/[0.06] rounded-xl text-sm">
              <FileText className="w-4 h-4 text-gray-500" />
              <span className="flex-1 truncate text-gray-300">{f.name}</span>
              <span className="text-xs text-gray-600">{(f.size / 1024).toFixed(0)} KB</span>
              <button onClick={(e) => { e.stopPropagation(); setFiles(fl => fl.filter((_, idx) => idx !== i)) }}
                className="p-0.5 hover:bg-white/[0.06] rounded">
                <X className="w-3.5 h-3.5 text-gray-500" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
