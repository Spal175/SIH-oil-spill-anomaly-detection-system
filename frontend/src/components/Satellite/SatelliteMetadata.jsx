function formatFileSize(bytes) {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function InfoRow({ label, value, muted = false }) {
  return (
    <div className="metadata-field">
      <span className="label-text text-gray-600">{label}</span>
      {muted ? (
        <span className="text-xs text-gray-700 italic">{value}</span>
      ) : (
        <span className="text-sm font-medium text-gray-100 break-all">{value}</span>
      )}
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-1 h-3.5 bg-accent/60 rounded-full" />
      <span className="label-text text-gray-400">{children}</span>
    </div>
  )
}

export default function SatelliteMetadata({ file }) {
  if (!file) return null

  const ext = file.name.slice(file.name.lastIndexOf('.') + 1).toUpperCase() || 'TIFF'

  return (
    <div className="card h-full flex flex-col appear">
      {/* Header */}
      <div className="card-header">
        <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
        </svg>
        <span className="label-text text-gray-400">Image Information</span>
      </div>

      {/* Body */}
      <div className="p-5 space-y-5 flex-1">
        {/* File info */}
        <section className="space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="label-text text-gray-600 mb-1.5">File Name</p>
              <p className="text-sm font-medium text-gray-100 break-all" title={file.name}>
                {file.name}
              </p>
            </div>
            <span className="badge flex-shrink-0 text-status-success border-status-success/30 bg-status-success/10">
              ✓ Ready
            </span>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <InfoRow label="Format" value={`GeoTIFF (.${ext.toLowerCase()})`} />
            <InfoRow label="File Size" value={formatFileSize(file.size)} />
          </div>
        </section>

        {/* Divider */}
        <div className="h-px bg-surface-600" />

        {/* Geospatial metadata */}
        <section className="space-y-4">
          <SectionTitle>Geospatial Metadata</SectionTitle>

          <div className="grid grid-cols-2 gap-4">
            <InfoRow label="Latitude" value="Not available" muted />
            <InfoRow label="Longitude" value="Not available" muted />
            <InfoRow label="CRS" value="Not available" muted />
            <InfoRow label="Resolution" value="Not available" muted />
          </div>

          <p className="text-[10px] text-gray-700 leading-relaxed">
            GeoTIFF metadata will populate here once backend parsing is connected.
          </p>
        </section>
      </div>
    </div>
  )
}