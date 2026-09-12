import { useState, useCallback } from 'react'
import SatelliteUpload from '../components/Satellite/SatelliteUpload'
import SatellitePreview from '../components/Satellite/SatellitePreview'
import SatelliteMetadata from '../components/Satellite/SatelliteMetadata'
import { analyzeTiff, formatDetectedAt, API_BASE } from '../api'

const STEPS = [
  { id: 1, label: 'Upload', desc: 'Select GeoTIFF' },
  { id: 2, label: 'Inspect', desc: 'Review & prepare' },
  { id: 3, label: 'Analyze', desc: 'Run detection' },
]

function StepTracker({ step }) {
  return (
    <div className="flex items-center gap-2">
      {STEPS.map((s, i) => {
        const done = s.id < step
        const active = s.id === step
        return (
          <div key={s.id} className="flex items-center gap-2">
            {i > 0 && (
              <span
                className={`h-px w-5 transition-colors duration-200 ${
                  done || active ? 'bg-accent/50' : 'bg-surface-600'
                }`}
              />
            )}
            <div
              className={`flex items-center gap-1.5 transition-colors duration-200 ${
                active ? 'text-sea' : done ? 'text-accent/80' : 'text-gray-600'
              }`}
            >
              <span
                className={`flex items-center justify-center w-4 h-4 rounded-full text-[9px] transition-colors duration-200 ${
                  active
                    ? 'bg-sea/15 text-sea border border-sea/30'
                    : done
                    ? 'bg-accent/15 text-accent'
                    : 'bg-surface-700 text-gray-500'
                }`}
              >
                {done ? '✓' : s.id}
              </span>
              <span className="text-[10px] font-mono uppercase tracking-wider">{s.label}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function StatChip({ label, value, accent = false }) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2.5 rounded-md bg-surface-800/70 border border-surface-700">
      <span className="label-text text-gray-600">{label}</span>
      <span className={`text-sm font-mono font-medium ${accent ? 'text-accent' : 'text-gray-200'}`}>
        {value}
      </span>
    </div>
  )
}

function SatelliteHeroGraphic() {
  return (
    <div className="satellite-hero-graphic hidden lg:block" aria-hidden="true">
      <span className="satellite-star satellite-star-one" />
      <span className="satellite-star satellite-star-two" />
      <span className="satellite-star satellite-star-three" />
      <span className="satellite-orbit satellite-orbit-wide" />
      <span className="satellite-orbit satellite-orbit-tight" />
      <span className="satellite-signal satellite-signal-one" />
      <span className="satellite-signal satellite-signal-two" />
      <svg className="satellite-art" viewBox="0 0 260 160" fill="none">
        <defs>
          <linearGradient id="satellite-panel" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#38bdf8" stopOpacity="0.9" />
            <stop offset="1" stopColor="#2563eb" stopOpacity="0.35" />
          </linearGradient>
          <linearGradient id="satellite-body" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#e0f2fe" />
            <stop offset="1" stopColor="#64748b" />
          </linearGradient>
        </defs>
        <g className="satellite-art-float" transform="translate(130 80) rotate(-16)">
          <path d="M-18-8 18-8 23 8-23 8Z" fill="url(#satellite-body)" stroke="#bae6fd" strokeWidth="1" />
          <path d="M-13-4 13-4 15 4-15 4Z" fill="#0f2940" stroke="#38bdf8" strokeWidth="0.8" />
          <circle cx="0" cy="0" r="3" fill="#38bdf8" opacity="0.9" />
          <path d="M-23 0h-21M23 0h21" stroke="#7dd3fc" strokeWidth="1.5" />
          <path d="M-44-13h21v26h-21zM23-13h21v26H23z" fill="url(#satellite-panel)" stroke="#7dd3fc" strokeWidth="1" />
          <path d="M-37-13v26M-30-13v26M-44-4h21M-44 5h21M30-13v26M37-13v26M23-4h21M23 5h21" stroke="#bae6fd" strokeOpacity="0.55" strokeWidth="0.7" />
          <path d="M0 8v17M-5 25h10" stroke="#bae6fd" strokeWidth="1.4" />
          <path d="M0-8V-25M-5-25h10" stroke="#bae6fd" strokeWidth="1.2" />
          <circle cy="-27" r="2" fill="#fbbf24" />
        </g>
      </svg>
      <span className="satellite-caption">ORBITAL SAR // LIVE TRACKING</span>
    </div>
  )
}

export default function Satellite() {
  const [selectedFile, setSelectedFile] = useState(null)
  const [analysisStatus, setAnalysisStatus] = useState(null)
  const [analysisResult, setAnalysisResult] = useState(null)
  const [analysisError, setAnalysisError] = useState(null)

  const handleFileSelect = useCallback((file) => {
    setSelectedFile(file)
    setAnalysisStatus(null)
    setAnalysisResult(null)
    setAnalysisError(null)
  }, [])

  const handleRemoveFile = useCallback(() => {
    setSelectedFile(null)
    setAnalysisStatus(null)
    setAnalysisResult(null)
    setAnalysisError(null)
  }, [])

  const handleAnalyze = useCallback(async () => {
    if (!selectedFile) return
    setAnalysisStatus('loading')
    setAnalysisResult(null)
    setAnalysisError(null)
    try {
      const result = await analyzeTiff(selectedFile)
      setAnalysisResult(result)
      setAnalysisStatus(result.spill ? 'detected' : 'clean')
    } catch (err) {
      setAnalysisError(err.message)
      setAnalysisStatus('error')
    }
  }, [selectedFile])

  const currentStep = !selectedFile ? 1 : ['loading', 'detected', 'clean', 'error'].includes(analysisStatus) ? 3 : 2

  return (
    <div className="space-y-6">
      {/* Hero header */}
      <header
        className="relative overflow-hidden rounded-xl border border-surface-600 bg-surface-800/60 px-6 py-5"
        style={{
          backgroundImage:
            'radial-gradient(600px 200px at 85% -20%, rgba(14,165,233,0.12), transparent 60%), radial-gradient(500px 180px at 15% -30%, rgba(59,130,246,0.08), transparent 60%)',
        }}
      >
        <div className="flex flex-wrap items-start justify-between gap-5 relative z-10 lg:pr-72">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <div className="w-1.5 h-6 rounded bg-accent" />
              <h1 className="text-xl font-semibold text-gray-100 tracking-wide uppercase">
                Satellite Imagery
              </h1>
              <span className="badge text-sea border-sea/30 bg-sea/10 ml-1">SAR</span>
            </div>
            <p className="text-sm font-medium text-gray-400 ml-4">
              Satellite SAR image workspace
            </p>
            <p className="text-xs text-gray-500 ml-4 mt-1">
              Upload and inspect GeoTIFF imagery before running oil-spill analysis.
            </p>
          </div>

          <div className="flex flex-col items-end gap-2.5">
            <StepTracker step={currentStep} />
          </div>
        </div>

        <SatelliteHeroGraphic />

        {/* Stat strip */}
        <div className="relative z-10 mt-5 pt-4 border-t border-surface-600/60 flex flex-wrap items-center gap-3">
          <StatChip label="Instrument" value="SAR" accent />
          <StatChip label="Format" value="GeoTIFF" />
          <StatChip label="Bands" value="Pending" />
          <StatChip label="Resolution" value="Pending" />
          <div className="flex-1" />
          <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-surface-900/60 border border-surface-700">
            <span className={`w-1.5 h-1.5 rounded-full ${selectedFile ? 'bg-status-success' : 'bg-status-warning'} animate-pulse`} />
            <span className="text-[10px] font-mono uppercase tracking-wider text-gray-500">
              {selectedFile ? 'File Acquired' : 'Awaiting Data'}
            </span>
          </div>
        </div>
      </header>

      {/* Body */}
      {!selectedFile ? (
        <SatelliteUpload onFileSelect={handleFileSelect} />
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-stretch">
            <div className="lg:col-span-2 min-w-0">
              <SatellitePreview file={selectedFile} />
            </div>
            <div className="lg:col-span-1 min-w-0">
              <SatelliteMetadata file={selectedFile} />
            </div>
          </div>

          <div
            className={`appear flex items-center gap-2.5 px-4 py-2.5 rounded-md border transition-colors duration-200 ${
              analysisStatus === 'loading'
                ? 'bg-status-info/10 border-status-info/20'
                : 'bg-surface-800/60 border-surface-600'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                analysisStatus === 'loading' ? 'bg-status-info' : 'bg-sea'
              } animate-pulse flex-shrink-0`}
            />
            <p className="text-xs text-gray-400">
              {analysisStatus === 'loading'
                ? 'Sending GeoTIFF to AI backend — running ML detection…'
                : 'GeoTIFF held locally. Run analysis to send it to the AI backend.'}
            </p>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="appear flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-t border-surface-700 pt-5">
        {selectedFile ? (
          <button
            onClick={handleRemoveFile}
            className="btn-danger inline-flex items-center gap-2 self-start"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
            </svg>
            Remove Image
          </button>
        ) : (
          <span className="hidden sm:block" />
        )}

        <button
          onClick={handleAnalyze}
          disabled={!selectedFile || analysisStatus === 'loading'}
          className="btn-primary inline-flex items-center gap-2 w-full sm:w-auto justify-center"
        >
          {analysisStatus === 'loading' ? (
            <>
              <span className="w-4 h-4 rounded-full border-2 border-current border-t-transparent animate-spin" />
              Analyzing…
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
              </svg>
              Analyze Satellite Image
            </>
          )}
        </button>
      </div>

      {/* Analyze result status */}
      {analysisStatus === 'detected' && analysisResult?.spill && (
        <div className="appear space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 px-4 py-3 rounded-md bg-status-error/10 border border-status-error/25">
            <div className="flex items-start gap-2.5">
              <svg className="w-5 h-5 text-status-error flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
              <div>
                <p className="text-sm font-medium text-status-error">Oil spill detected</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Detection broadcast live to the OceanWatch dashboard at{' '}
                  <span className="font-mono">{API_BASE}</span>.
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  Spill ID{' '}
                  <span className="font-mono text-gray-300">{analysisResult.spill.id}</span> · Detected{' '}
                  {formatDetectedAt(analysisResult.spill.detected_at)}
                </p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 sm:flex-none">
              {[
                ['Latitude', analysisResult.spill.latitude?.toFixed(4), 'text-gray-200'],
                ['Longitude', analysisResult.spill.longitude?.toFixed(4), 'text-gray-200'],
                ['Confidence', analysisResult.spill.confidence != null ? `${(analysisResult.spill.confidence * 100).toFixed(0)}%` : '—', 'text-status-error'],
              ].map(([label, value, color]) => (
                <div key={label} className="flex flex-col gap-0.5 px-3 py-2 rounded-md bg-surface-900/60 border border-surface-700">
                  <span className="label-text text-gray-600">{label}</span>
                  <span className={`text-xs font-mono font-medium ${color}`}>{value}</span>
                </div>
              ))}
            </div>
          </div>

          {analysisResult.candidate_vessels?.length > 0 && (
            <div className="rounded-md border border-surface-600 bg-surface-800/60 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-surface-700 flex items-center justify-between">
                <span className="text-[11px] font-mono uppercase tracking-widest text-gray-500">Attributed Vessels</span>
                <span className="badge text-status-warning border-status-warning/30 bg-status-warning/10">{analysisResult.candidate_vessels.length}</span>
              </div>
              <div className="divide-y divide-surface-700/60">
                {analysisResult.candidate_vessels.map((c) => (
                  <div key={c.mmsi} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <div className="min-w-0">
                      <p className="text-sm text-gray-200 truncate">
                        <span className="font-mono text-[10px] text-accent mr-2">#{c.rank}</span>
                        {c.ship_name || `MMSI ${c.mmsi}`}
                      </p>
                      <p className="text-[10px] font-mono text-gray-500 mt-0.5">
                        {c.mmsi} · {c.ship_type || 'Unknown type'}
                      </p>
                    </div>
                    <div className="flex items-center gap-4 flex-none">
                      <span className="text-[10px] font-mono text-gray-500">{c.distance_km != null ? `${c.distance_km.toFixed(2)} km` : '—'}</span>
                      <span className="text-[10px] font-mono text-gray-500">{c.time_difference_minutes != null ? `${c.time_difference_minutes} min` : '—'}</span>
                      <span className={`text-[10px] font-mono ${c.attribution_score != null ? 'text-status-error' : 'text-gray-600'}`}>
                        {c.attribution_score != null ? `${(c.attribution_score * 100).toFixed(0)}%` : '—'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {analysisStatus === 'clean' && (
        <div className="appear flex items-center gap-2.5 px-4 py-3 rounded-md bg-surface-800 border border-surface-600">
          <svg className="w-4 h-4 text-status-success flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-sm text-gray-300">
            <span className="font-medium text-status-success">No oil spill detected.</span>{' '}
            <span className="text-gray-500">The model found nothing suspicious in this scene.</span>
          </p>
        </div>
      )}

      {analysisStatus === 'error' && (
        <div className="appear flex items-center gap-2.5 px-4 py-3 rounded-md bg-status-error/10 border border-status-error/25">
          <svg className="w-4 h-4 text-status-error flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <p className="text-sm text-gray-300">
            <span className="font-medium text-status-error">Analysis failed.</span>{' '}
            <span className="text-gray-500">{analysisError}</span>
          </p>
        </div>
      )}
    </div>
  )
}