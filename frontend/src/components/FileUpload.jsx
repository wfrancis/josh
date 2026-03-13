import { useState, useRef, useCallback } from 'react'
import { Upload, FileSpreadsheet, FileText, X, CheckCircle2, Loader2 } from 'lucide-react'

export default function FileUpload({
  accept, multiple = false, onUpload,
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
    if (droppedFiles.length) { setFiles(droppedFiles); onUpload?.(multiple ? droppedFiles : droppedFiles[0]) }
  }, [onUpload, multiple])

  const handleChange = (e) => {
    const selected = Array.from(e.target.files)
    if (selected.length) { setFiles(selected); onUpload?.(multiple ? selected : selected[0]) }
  }

  const Icon = CustomIcon || (accept?.includes('.xls') ? FileSpreadsheet : FileText)

  if (success) {
    return (
      <div className="upload-zone !border-emerald-500/30 !bg-emerald-500/[0.04] text-center">
        <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
        <p className="text-sm font-medium text-emerald-300">{successMessage}</p>
        <button
          onClick={() => { setFiles([]); inputRef.current && (inputRef.current.value = '') }}
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
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="w-10 h-10 text-si-bright animate-spin" />
            <p className="text-sm text-gray-400">Processing...</p>
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
