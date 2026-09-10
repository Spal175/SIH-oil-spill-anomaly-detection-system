import { useState, useEffect } from 'react'

const ZOOM_LEVELS = [0.5, 0.75, 1, 1.5, 2, 3, 4]
const FIT_INDEX = ZOOM_LEVELS.indexOf(1)

export default function SatellitePreview({ file }) {
  const [previewUrl, setPreviewUrl] = useState(null)
  const [renderFailed, setRenderFailed] = useState(false)
  const [zoomIndex, setZoomIndex] = useState(FIT_INDEX)

  useEffect(() => {
    setPreviewUrl(null)
    setRenderFailed(false)
    setZoomIndex(FIT_INDEX)
    if (!file) return undefined

    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => {
      URL.revokeObjectURL(url)
    }
  }, [file])

  if (!file) return null

  const zoom = ZOOM_LEVELS[zoomIndex]
  const canZoomIn = zoomIndex < ZOOM_LEVELS.length - 1
  const canZoomOut = zoomIndex > 0
  const isFit = zoomIndex === FIT_INDEX
  const showPlaceholder = !previewUrl || renderFailed

  const zoomIn = () => {
    if (canZoomIn) setZoomIndex((i) => i + 1)
  }
  const zoomOut = () => {
    if (canZoomOut) setZoomIndex((i) => i - 1)
  }
  const fitView = () => setZoomIndex(FIT_INDEX)

  return (
    <div className="card h-full flex flex-col appear overflow-hidden">
      {/* Header */}
      <div className="card-header flex-wrap gap-y-2">
        <svg className="w-4 h-4 text-sea" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z" />
        </svg>
        <span className="label-text text-gray-400">Satellite Preview</span>

        <span className="badge ml-auto text-sea border-sea/25 bg-sea/5">TIFF</span>

        {/* Controls */}
        <div className="flex items-center gap-1.5 ml-2">
          <button
            type="button"
            className="icon-btn"
            onClick={zoomOut}
            disabled={!canZoomOut}
            title="Zoom out"
            aria-label="Zoom out"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M18 12H6" />
            </svg>
          </button>
          <span className="w-10 text-center text-[10px] font-mono text-gray-500">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            className="icon-btn"
            onClick={zoomIn}
            disabled={!canZoomIn}
            title="Zoom in"
            aria-label="Zoom in"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12M6 12h12" />
            </svg>
          </button>
          <button
            type="button"
            className={`icon-btn text-[10px] font-mono ${isFit ? 'text-sea' : ''}`}
            onClick={fitView}
            disabled={isFit}
            title="Fit to view"
            aria-label="Fit to view"
          >
            F
          </button>
        </div>
      </div>

      {/* Viewer */}
      <div className="viewer-grid relative overflow-hidden flex-1 rounded-b-lg" style={{ minHeight: 440 }}>
        {/* Image */}
        {!showPlaceholder && (
          <img
            src={previewUrl}
            alt={`Preview of ${file.name}`}
            className="absolute inset-0 w-full h-full object-contain transition-transform duration-150 ease-out"
            style={{ transform: `scale(${zoom})`, transformOrigin: 'center' }}
            onError={() => setRenderFailed(true)}
          />
        )}

        {/* Placeholder */}
        {showPlaceholder && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3.5 text-center px-8">
            <div className="flex items-center justify-center w-20 h-20 rounded-full bg-surface-800/80 border border-sea/20">
              <svg className="w-10 h-10 text-sea/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.4}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-medium text-gray-200">TIFF Selected</p>
              <p className="text-xs text-gray-500 mt-1 max-w-sm leading-relaxed">
                GeoTIFF preview is not supported in this browser. The file is
                selected and ready for analysis.
              </p>
            </div>
            <span className="badge text-gray-500 border-surface-600 bg-surface-800/60">
              SAR / GEOTIFF
            </span>
          </div>
        )}

        {/* Scanlines */}
        <div className="scanlines absolute inset-0 pointer-events-none" />
        <div className="scan-sweep absolute inset-0 rounded-b-lg" />

        {/* Corner brackets */}
        <div className="absolute top-3 left-3 w-5 h-5 border-t border-l border-sea/30 pointer-events-none" />
        <div className="absolute top-3 right-3 w-5 h-5 border-t border-r border-sea/30 pointer-events-none" />
        <div className="absolute bottom-3 left-3 w-5 h-5 border-b border-l border-sea/30 pointer-events-none" />
        <div className="absolute bottom-3 right-3 w-5 h-5 border-b border-r border-sea/30 pointer-events-none" />

        {/* Center crosshair */}
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none">
          <div className="w-6 h-6 relative">
            <span className="absolute left-1/2 top-0 -translate-x-1/2 w-px h-full bg-sea/20" />
            <span className="absolute top-1/2 left-0 -translate-y-1/2 h-px w-full bg-sea/20" />
            <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-sea/40" />
          </div>
        </div>

        {/* Ruler ticks */}
        <div className="absolute top-1/2 -translate-y-1/2 -left-1 flex flex-col justify-between h-16 text-[8px] font-mono text-sea/40">
          <span>▪</span>
          <span>▪▪</span>
          <span>▪</span>
        </div>
        <div className="absolute left-1/2 -translate-x-1/2 -top-1 flex flex-row justify-between w-16 text-[8px] font-mono text-sea/40">
          <span>▪</span>
          <span>▪▪</span>
          <span>▪</span>
        </div>

        {/* Bottom status strip */}
        <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 px-4 py-2.5 bg-gradient-to-t from-surface-900 to-transparent">
          <div className="flex items-center gap-2 min-w-0">
            <div className={`w-1.5 h-1.5 rounded-full ${showPlaceholder ? 'bg-sea' : 'bg-status-success'} animate-pulse flex-shrink-0`} />
            <span className="text-[10px] font-mono text-gray-400 truncate" title={file.name}>
              {showPlaceholder ? 'TIFF ready for analysis' : 'Rendered preview'}
            </span>
          </div>
          <div className="flex items-center gap-2 text-[10px] font-mono text-gray-600 flex-shrink-0">
            <span>LAT --</span>
            <span className="text-gray-700">|</span>
            <span>LON --</span>
            <span className="text-gray-700">|</span>
            <span>CRS --</span>
          </div>
        </div>
      </div>
    </div>
  )
}