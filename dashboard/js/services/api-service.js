/**
 * api-service.js
 * REST API client for the AI backend (http://localhost:8000).
 *
 * Endpoints used:
 *   GET  /health                        → { status, database, ... }
 *   POST /oil-spills/analyze            → OilSpillAnalyzeResponse
 *   GET  /oil-spills/{spill_id}         → OilSpillDetailResponse
 *   GET  /oil-spills/{spill_id}/vessels → CandidateVessel[]
 *   GET  /vessels/{mmsi}                → VesselDetail
 *   GET  /vessels/{mmsi}/trajectory     → VesselTrajectoryResponse
 */

export const API_BASE_URL = 'http://localhost:8000';

async function request(path, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      ...options.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch { /* ignore */ }
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }

  // 204 No Content
  if (response.status === 204) return null;
  return response.json();
}

/**
 * Health check — returns { status, database, version, ... } or throws.
 */
export async function getHealth() {
  return request('/health');
}

/**
 * GET /oil-spills
 * Returns stored oil spills, most recent first (no attribution detail):
 * [{ id, latitude, longitude, detected_at, confidence, area, crs, region_count, created_at }]
 */
export async function getSpills() {
  return request('/oil-spills');
}

/**
 * GET /oil-spills/{spill_id}
 * Returns stored spill detail + attributed candidate vessels.
 */
export async function getSpillDetail(spillId) {
  return request(`/oil-spills/${encodeURIComponent(spillId)}`);
}

/**
 * GET /oil-spills/{spill_id}/vessels
 * Returns the attributed candidate vessels for a stored spill.
 */
export async function getSpillVessels(spillId) {
  return request(`/oil-spills/${encodeURIComponent(spillId)}/vessels`);
}

/**
 * GET /vessels/{mmsi}
 * Returns static vessel info: { mmsi, ship_name, ship_type, imo, created_at }.
 */
export async function getVessel(mmsi) {
  return request(`/vessels/${encodeURIComponent(mmsi)}`);
}

/**
 * GET /vessels/{mmsi}/trajectory
 * Returns { mmsi, ship_name, points: [{timestamp, latitude, longitude, sog, cog, heading}] }
 * Optional ISO-8601 start/end query params.
 */
export async function getVesselTrajectory(mmsi, { start, end } = {}) {
  const params = new URLSearchParams();
  if (start) params.set('start', start);
  if (end)   params.set('end',   end);
  const qs = params.toString() ? `?${params}` : '';
  return request(`/vessels/${encodeURIComponent(mmsi)}/trajectory${qs}`);
}
