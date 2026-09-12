export const API_BASE = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export async function analyzeTiff(file, { threshold, minAreaPx } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (threshold !== undefined && threshold !== null) form.append('threshold', String(threshold))
  if (minAreaPx !== undefined && minAreaPx !== null) form.append('min_area_px', String(minAreaPx))

  let res
  try {
    res = await fetch(`${API_BASE}/oil-spills/analyze`, { method: 'POST', body: form })
  } catch (err) {
    throw new Error(`Cannot reach backend at ${API_BASE} (${err.message})`)
  }

  let body
  try {
    body = await res.json()
  } catch {
    body = null
  }

  if (!res.ok) {
    throw new Error(body?.detail || `Analysis failed (HTTP ${res.status})`)
  }
  return body
}

export async function checkHealth() {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 4000)
    const res = await fetch(`${API_BASE}/health`, { signal: controller.signal })
    clearTimeout(timer)
    return res.ok
  } catch {
    return false
  }
}

export function formatDetectedAt(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-GB', { hour12: false })
}