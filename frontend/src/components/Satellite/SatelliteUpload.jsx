import { useState, useRef, useCallback } from 'react'

const ACCEPTED_TYPES = ['image/tiff', 'image/x-tiff']
const ACCEPTED_EXTENSIONS = ['.tif', '.tiff']
const MAX_FILE_SIZE_MB = 200

function getFileExtension(name) {
  const idx = name.lastIndexOf('.')
  return idx >= 0 ? name.slice(idx).toLowerCase() : ''
}

function isValidTiffFile(file) {
  const ext = getFileExtension(file.name)
  if (ACCEPTED_EXTENSIONS.includes(ext)) return true
  if (ACCEPTED_TYPES.includes(file.type)) return true
  return false
}

function SatelliteIcon({ className = '' }) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="8.5" y="10.5" width="7" height="7" rx="1.2" />
      <circle cx="12" cy="14" r="1.8" />
      <rect x="5" y="13.5" width="2.6" height="1.8" rx="0.5" />
      <rect x="16.4" y="13.5" width="2.6" height="1.8" rx="0.5" />
      <path d="M15.5 10.5 18 7.5" />
      <circle cx="18.6" cy="6.8" r="1.1" />
      <path d="M12 17.5v2.2" />
    </svg>
  )
}

export default function SatelliteUpload({ onFileSelect }) {
  const [isDragging, setIsDragging] = useState(false)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  const processFile = useCallback((file) => {
    setError(null)

    if (!isValidTiffFile(file)) {
      setError({
        title: 'Unsupported file format',
        message: 'Please upload a .TIF or .TIFF file.',
      })
      return
    }

    const sizeMB = file.size / (1024 * 1024)
    if (sizeMB > MAX_FILE_SIZE_MB) {
      setError({
        title: 'File size exceeds limit',
        message: `Maximum allowed size is ${MAX_FILE_SIZE_MB} MB.`,
      })
      return
    }

    onFileSelect(file)
  }, [onFileSelect])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    setError(null)

    const files = e.dataTransfer.files
    if (files.length > 0) {
      processFile(files[0])
    }
  }, [processFile])

  const handleFileInput = useCallback((e) => {
    const files = e.target.files
    if (files.length > 0) {
      processFile(files[0])
    }
    e.target.value = ''
  }, [processFile])

  const handleClick = () => {
    inputRef.current?.click()
  }

  return (
    <section className="w-full space-y-2">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
        className={`
          upload-zone relative flex flex-col items-center justify-center gap-4
          px-6 py-10 text-center overflow-hidden
          transition-[border-color,background-color] duration-200
          ${isDragging ? 'upload-zone-active' : ''}
        `}
        style={{ minHeight: 290 }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".tif,.tiff,image/tiff,image/x-tiff"
          onChange={handleFileInput}
          className="hidden"
        />

        {/* Radar/scan decoration */}
        <div className="absolute -top-20 -right-20 w-56 h-56 rounded-full border border-sea/10" />
        <div className="absolute -top-14 -right-14 w-40 h-40 rounded-full border border-sea/10" />
        <div className="absolute -bottom-24 -left-20 w-64 h-64 rounded-full border border-accent/10" />
        <div className="scan-sweep absolute inset-0" />

        {/* Icon */}
        <div className={`
          relative flex items-center justify-center w-16 h-16 rounded-xl
          ${isDragging ? 'bg-accent/15' : 'bg-surface-700/70'}
          transition-all duration-200
        `}>
          <SatelliteIcon
            className={`w-9 h-9 transition-colors duration-200 ${isDragging ? 'text-accent' : 'text-sea'}`}
          />
          {isDragging && (
            <div className="absolute -inset-1 rounded-xl border border-accent/40 animate-pulse" />
          )}
        </div>

        <div className="space-y-1.5 relative z-10">
          <h2 className="text-base font-semibold text-gray-100 tracking-wide">
            Upload Satellite Image
          </h2>
          <p className="text-sm text-gray-500">
            {isDragging
              ? 'Drop the file here to select it'
              : 'Drop your GeoTIFF here or browse from your device'}
          </p>
        </div>

        <button
          type="button"
          className="btn-secondary relative z-10"
          onClick={(e) => {
            e.stopPropagation()
            handleClick()
          }}
        >
          Browse Files
        </button>

        <div className="flex items-center gap-2 text-[10px] font-mono text-gray-600 relative z-10">
          <span className="px-1.5 py-0.5 bg-surface-700 rounded text-gray-500">.TIF</span>
          <span className="px-1.5 py-0.5 bg-surface-700 rounded text-gray-500">.TIFF</span>
          <span className="text-gray-700">•</span>
          <span>Max {MAX_FILE_SIZE_MB} MB</span>
        </div>
      </div>

      {error && (
        <div
          className="appear mt-3 flex items-start gap-3 px-4 py-3 rounded-md bg-status-error/5 border border-status-error/20"
          role="alert"
        >
          <svg
            className="w-4 h-4 text-status-error flex-shrink-0 mt-0.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-status-error">{error.title}</p>
            <p className="text-xs text-gray-400">{error.message}</p>
          </div>
        </div>
      )}
    </section>
  )
}