/**
 * js/app.js
 * OceanWatch Maritime Surveillance Dashboard
 *
 * Coordinates Leaflet MapManager, AIS WebSocket stream, AI REST API,
 * spill analysis, vessel tracking, detail panels, modals, and toasts.
 */

import {
  getHealth,
  getSpills,
  getSpillDetail,
  getSpillVessels,
  getVessel,
  getVesselTrajectory,
} from './services/api-service.js';

import {
  AISConnection,
  getShipTypeInfo,
} from './services/ais-service.js';

import { MapManager } from './components/map-manager.js';

// ── State Management ─────────────────────────────────────────────────────────

const state = {
  mapManager: null,
  aisConnection: null,
  vessels: new Map(),        // mmsi (number) -> { latestPos, element, ... }
  spills: new Map(),         // spillId -> { spill, candidate_vessels }
  selectedVesselMmsi: null,
  selectedSpillId: null,
  activeTrajectoryLayer: null,
  healthPollTimer: null,
  spillPollTimer: null,
  spillsSyncedOnce: false,
  sidebarThrottleTimer: null,
  pendingSidebarUpdates: new Set(),
};

// ── DOM Element Selectors (with resilient fallbacks) ──────────────────────────

const dom = {
  // Map container
  mapContainer: () => document.getElementById('map') || document.getElementById('map-container'),
  mapCoords: () => document.getElementById('map-coords'),

  // Controls
  btnFitAoi: () => document.getElementById('btn-fit-aoi') || document.getElementById('fit-aoi') || document.querySelector('[data-action="fit-aoi"]'),
  btnToggleTrails: () => document.getElementById('btn-toggle-trails') || document.getElementById('toggle-trails') || document.querySelector('[data-action="toggle-trails"]'),

  // Backend & AIS status
  backendDot: () => document.getElementById('api-dot') || document.getElementById('backend-status-dot') || document.querySelector('.backend-status-dot') || document.getElementById('backend-dot'),
  backendText: () => document.getElementById('api-status-text') || document.getElementById('backend-status-text') || document.querySelector('.backend-status-text') || document.getElementById('backend-status'),
  backendBadge: () => document.getElementById('backend-badge') || document.querySelector('.backend-badge'),

  aisDot: () => document.getElementById('ais-status-dot') || document.querySelector('.ais-status-dot') || document.getElementById('ws-status-dot'),
  aisText: () => document.getElementById('ais-status-text') || document.querySelector('.ais-status-text') || document.getElementById('ws-status-text') || document.getElementById('ais-status'),
  aisBadge: () => document.getElementById('ais-badge') || document.querySelector('.ais-badge'),

  vesselCount: () => document.getElementById('vessels-count') || document.getElementById('vessel-count') || document.getElementById('stat-vessels') || document.querySelector('.vessel-count'),
  vesselCountBadge: () => document.getElementById('vessel-count-badge') || document.querySelector('.vessel-count-badge'),
  msgsPerSec: () => document.getElementById('msg-rate') || document.getElementById('stat-msgs') || document.getElementById('msgs-per-sec') || document.getElementById('ais-rate') || document.querySelector('.msgs-per-sec'),
  spillCount: () => document.getElementById('spills-count') || document.getElementById('spill-count') || document.getElementById('stat-spills') || document.querySelector('.spill-count'),
  spillCountBadge: () => document.getElementById('spill-count-badge') || document.querySelector('.spill-count-badge'),

  // Lists & Sidebars
  vesselList: () => document.getElementById('vessel-list') || document.getElementById('vessels-list') || document.querySelector('.vessel-list'),
  spillList: () => document.getElementById('spill-list') || document.getElementById('spills-list') || document.querySelector('.spill-list'),

  // Right-side Detail Panel
  detailPanel: () => document.getElementById('detail-panel') || document.getElementById('details-panel') || document.querySelector('.detail-panel'),
  detailPanelTitle: () => document.getElementById('detail-panel-title') || document.querySelector('.detail-panel-title'),
  detailPanelContent: () => document.getElementById('panel-content') || document.getElementById('detail-panel-content') || document.querySelector('.detail-panel-content'),
  detailCloseBtn: () => document.getElementById('btn-close-panel') || document.getElementById('btn-close-detail') || document.getElementById('detail-close') || document.querySelector('.detail-close') || document.querySelector('[data-action="close-detail"]'),
  candidateVesselsSection: () => document.getElementById('candidate-vessels-section') || document.querySelector('.candidate-vessels-section'),
  candidateVesselsList: () => document.getElementById('candidate-vessels-list') || document.querySelector('.candidate-vessels-list'),



  // Toasts
  toastContainer: () => document.getElementById('toast-container'),
};

// ── Toasts Utility ────────────────────────────────────────────────────────────

function showToast(message, type = 'info', durationMs = 4000) {
  let container = dom.toastContainer();
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', 'alert');

  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ',
  };

  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || 'ℹ'}</span>
    <span class="toast-message">${escapeHtml(message)}</span>
    <button class="toast-close" aria-label="Close">&times;</button>
  `;

  const closeBtn = toast.querySelector('.toast-close');
  const dismiss = () => {
    if (!toast.parentNode) return;
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 250);
  };

  closeBtn?.addEventListener('click', dismiss);
  container.appendChild(toast);

  if (durationMs > 0) {
    setTimeout(dismiss, durationMs);
  }
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function formatDate(isoOrDate) {
  if (!isoOrDate) return '—';
  try {
    const d = new Date(isoOrDate);
    if (isNaN(d.getTime())) return String(isoOrDate);
    return d.toUTCString().replace('GMT', 'UTC');
  } catch {
    return String(isoOrDate);
  }
}

// ── 1. Initialization ────────────────────────────────────────────────────────

function initDashboard() {
  initMap();
  initControls();
  initDetailPanel();
  initBackendHealth();
  initAISStream();
  initSpillPolling();
  updateVesselCountDisplay();
  updateSpillCountDisplay();
}

function initMap() {
  const container = dom.mapContainer();
  const containerId = container ? container.id : 'map';

  state.mapManager = new MapManager(containerId);
  state.mapManager.init();

  // Connect clicks from Leaflet markers
  state.mapManager.onVesselClick = (mmsi, pos) => {
    selectVessel(mmsi, pos);
  };

  state.mapManager.onSpillClick = (spillId, spill) => {
    selectSpill(spillId, spill);
  };
}

function initControls() {
  // Fit to AOI
  const btnFitAoi = dom.btnFitAoi();
  if (btnFitAoi) {
    btnFitAoi.addEventListener('click', () => {
      state.mapManager?.fitToAOI();
    });
  }

  // Toggle Trails
  const btnToggleTrails = dom.btnToggleTrails();
  if (btnToggleTrails) {
    btnToggleTrails.addEventListener('click', () => {
      const visible = state.mapManager?.toggleTrails();
      btnToggleTrails.classList.toggle('active', !!visible);
      showToast(`Vessel trails ${visible ? 'enabled' : 'disabled'}`, 'info', 2000);
    });
  }
}

// ── 2. Backend Health ────────────────────────────────────────────────────────

let lastBackendStatus = null;

async function checkBackendHealth() {
  const dot = dom.backendDot();
  const text = dom.backendText();
  const badge = dom.backendBadge();

  try {
    const health = await getHealth();
    const isHealthy = health && (health.status === 'ok' || health.status === 'healthy' || health.database !== 'error');

    if (dot) {
      dot.className = 'status-dot ' + (isHealthy ? 'status-connected online' : 'status-warning');
    }
    if (text) {
      text.textContent = isHealthy ? 'Connected' : (health?.status || 'Degraded');
    }
    if (badge) {
      badge.classList.remove('offline', 'error');
      badge.classList.add(isHealthy ? 'online' : 'warning');
    }

    if (lastBackendStatus !== 'connected' && isHealthy) {
      lastBackendStatus = 'connected';
      showToast('AI Backend connected', 'success', 3000);
    }
  } catch (err) {
    if (dot) {
      dot.className = 'status-dot status-disconnected offline error';
    }
    if (text) {
      text.textContent = 'Disconnected';
    }
    if (badge) {
      badge.classList.remove('online', 'warning');
      badge.classList.add('offline');
    }

    if (lastBackendStatus !== 'disconnected') {
      lastBackendStatus = 'disconnected';
      showToast('AI Backend unavailable (http://localhost:8000)', 'error', 5000);
    }
  }
}

function initBackendHealth() {
  checkBackendHealth();
  state.healthPollTimer = setInterval(checkBackendHealth, 12000);
}

// ── 3. Live AIS Vessel Tracking ──────────────────────────────────────────────

function initAISStream() {
  const aisDot = dom.aisDot();
  const aisText = dom.aisText();
  const aisBadge = dom.aisBadge();

  state.aisConnection = new AISConnection();

  state.aisConnection.onStatusChange = (status) => {
    switch (status) {
      case 'connected':
        if (aisDot) aisDot.className = 'status-dot status-connected online';
        if (aisText) aisText.textContent = 'Streaming';
        if (aisBadge) {
          aisBadge.classList.remove('offline', 'warning');
          aisBadge.classList.add('online');
        }
        showToast('AIS live stream connected', 'success', 3000);
        break;

      case 'connecting':
        if (aisDot) aisDot.className = 'status-dot status-warning';
        if (aisText) aisText.textContent = 'Connecting...';
        if (aisBadge) {
          aisBadge.classList.remove('online', 'offline');
          aisBadge.classList.add('warning');
        }
        break;

      case 'disconnected':
      case 'error':
      default:
        if (aisDot) aisDot.className = 'status-dot status-disconnected offline';
        if (aisText) aisText.textContent = 'Disconnected';
        if (aisBadge) {
          aisBadge.classList.remove('online', 'warning');
          aisBadge.classList.add('offline');
        }
        break;
    }
  };

  state.aisConnection.onStats = ({ messagesPerSecond }) => {
    const el = dom.msgsPerSec();
    if (el) {
      el.textContent = `${messagesPerSecond} msg/s`;
    }
  };

  state.aisConnection.onVesselUpdate = (pos) => {
    handleVesselPositionUpdate(pos);
  };

  state.aisConnection.connect();
}

function handleVesselPositionUpdate(pos) {
  if (!pos || !pos.mmsi) return;

  const mmsi = pos.mmsi;
  const existing = state.vessels.get(mmsi);

  state.vessels.set(mmsi, {
    ...(existing || {}),
    latestPos: pos,
    updatedAt: Date.now(),
  });

  // Update marker on Leaflet map
  state.mapManager?.updateVessel(pos);

  // Update total vessel count display
  updateVesselCountDisplay();

  // Queue throttled sidebar row update for smooth real-time DOM rendering
  state.pendingSidebarUpdates.add(mmsi);
  scheduleSidebarRender();

  // If this vessel is currently active in detail panel, refresh coordinates and live metrics
  if (state.selectedVesselMmsi === mmsi) {
    updateVesselLiveDetailFields(pos);
  }
}

function scheduleSidebarRender() {
  if (state.sidebarThrottleTimer) return;
  state.sidebarThrottleTimer = setTimeout(() => {
    flushSidebarUpdates();
    state.sidebarThrottleTimer = null;
  }, 150);
}

function flushSidebarUpdates() {
  const vesselList = dom.vesselList();
  if (!vesselList || state.pendingSidebarUpdates.size === 0) {
    state.pendingSidebarUpdates.clear();
    return;
  }

  // Remove empty placeholder if any
  const emptyPlaceholder = vesselList.querySelector('.empty-state, .placeholder, .list-empty');
  if (emptyPlaceholder && state.vessels.size > 0) {
    emptyPlaceholder.remove();
  }

  for (const mmsi of state.pendingSidebarUpdates) {
    const vessel = state.vessels.get(mmsi);
    if (!vessel || !vessel.latestPos) continue;

    const pos = vessel.latestPos;
    const typeInfo = getShipTypeInfo(pos.shipType);
    const displayName = pos.shipName ? pos.shipName.replace(/^DEMO /, '') : `MMSI ${pos.mmsi}`;
    const sogText = pos.sog != null ? `${Number(pos.sog).toFixed(1)} kn` : '—';
    const headingText = pos.heading != null && pos.heading >= 0 ? `${pos.heading}°` : (pos.cog != null ? `${Number(pos.cog).toFixed(0)}°` : '—');

    let row = document.getElementById(`vessel-item-${mmsi}`);
    if (!row) {
      row = document.createElement('div');
      row.id = `vessel-item-${mmsi}`;
      row.className = 'vessel-item' + (state.selectedVesselMmsi === mmsi ? ' selected active' : '');
      row.dataset.mmsi = String(mmsi);

      row.addEventListener('click', () => {
        selectVessel(mmsi, pos);
      });

      vesselList.appendChild(row);
    }

    row.innerHTML = `
      <span class="vessel-icon" style="background:${typeInfo.color}26;">${typeInfo.emoji}</span>
      <div class="vessel-info">
        <div class="vessel-name" title="${escapeHtml(pos.shipName || '')}">${escapeHtml(displayName)}</div>
        <div class="vessel-meta">
          <span>MMSI ${pos.mmsi}</span>
          <span>${headingText}</span>
        </div>
      </div>
      <span class="vessel-speed">${sogText}</span>
    `;
  }

  state.pendingSidebarUpdates.clear();
}

// ── 4b. Oil Spill Polling (AI backend detections) ────────────────────────────

const SPILL_POLL_INTERVAL_MS = 3000;

function initSpillPolling() {
  pollSpills();
  state.spillPollTimer = setInterval(pollSpills, SPILL_POLL_INTERVAL_MS);
}

async function pollSpills() {
  let spills;
  try {
    spills = await getSpills();
  } catch (err) {
    // Backend (or its DB) is unreachable right now — try again next tick.
    return;
  }

  const seen = new Set();
  for (const item of spills || []) {
    if (!item || !item.id) continue;
    seen.add(item.id);

    if (state.spills.has(item.id)) continue;

    const spill = {
      id: item.id,
      latitude: item.latitude,
      longitude: item.longitude,
      detected_at: item.detected_at,
      confidence: item.confidence,
      area: item.area,
      crs: item.crs,
      region_count: item.region_count,
    };

    state.spills.set(item.id, { spill, candidate_vessels: [] });
    state.mapManager?.addSpill(spill);
    addSpillToSidebar(spill);

    // Only interrupt with toasts for new detections after the first sync.
    if (state.spillsSyncedOnce) {
      const confPercent = Math.round((spill.confidence ?? 0) * 100);
      showToast(
        `Oil spill detected: ${spill.id} (${confPercent}% confidence)`,
        'warning',
        6000
      );
    }
  }
  state.spillsSyncedOnce = true;

  // Remove spills that disappeared on the backend (e.g. DB reset).
  for (const id of [...state.spills.keys()]) {
    if (seen.has(id)) continue;
    state.spills.delete(id);
    state.mapManager?.removeSpill(id);
    const el = document.getElementById(`spill-item-${id}`);
    el?.remove();
  }

  updateSpillCountDisplay();
}

function addSpillToSidebar(spill) {
  const list = dom.spillList();
  if (!list || !spill || !spill.id) return;

  const empty = list.querySelector('.empty-state, .placeholder, .list-empty');
  if (empty && state.spills.size > 0) empty.remove();

  let item = document.getElementById(`spill-item-${spill.id}`);
  if (!item) {
    item = document.createElement('div');
    item.id = `spill-item-${spill.id}`;
    item.className = 'spill-item';
    item.dataset.spillId = spill.id;
    item.addEventListener('click', () => selectSpill(spill.id, spill));
    list.prepend(item);
  }

  const confPercent = Math.round((spill.confidence ?? 0) * 100);
  const areaText = spill.area ? `${Math.round(spill.area).toLocaleString()} m²` : '—';
  const lat = spill.latitude != null ? spill.latitude.toFixed(4) : '—';
  const lon = spill.longitude != null ? spill.longitude.toFixed(4) : '—';

  item.innerHTML = `
    <div class="spill-icon-wrap">🛢️</div>
    <div class="spill-info">
      <div class="spill-id" title="${escapeHtml(spill.id)}">${escapeHtml(spill.id)}</div>
      <div class="spill-coords">${lat}, ${lon}</div>
      <div class="spill-time">${formatDate(spill.detected_at)} · ${areaText}</div>
    </div>
    <div class="spill-confidence" style="color:${confPercent >= 80 ? 'var(--spill-orange)' : 'var(--accent-cyan)'}">
      ${confPercent}%
    </div>
  `;
}

function updateSpillCountDisplay() {
  const count = state.mapManager?.getSpillCount() ?? state.spills.size;
  const el = dom.spillCount();
  if (el) el.textContent = count;
  const badge = dom.spillCountBadge();
  if (badge) badge.textContent = count;
}

function updateVesselCountDisplay() {
  const count = state.mapManager?.getVesselCount() ?? state.vessels.size;
  const el = dom.vesselCount();
  if (el) el.textContent = count;
  const badge = dom.vesselCountBadge();
  if (badge) badge.textContent = count;
}

// ── 5. Vessel Selection & Detail Panel ────────────────────────────────────────

async function selectVessel(mmsi, livePos = null) {
  cleanupSelection();

  state.selectedVesselMmsi = mmsi;
  state.selectedSpillId = null;

  // Highlight map marker & pan
  state.mapManager?.selectVessel(mmsi);

  // Highlight sidebar item
  document.querySelectorAll('.vessel-item').forEach((item) => {
    item.classList.toggle('selected', item.dataset.mmsi === String(mmsi));
    item.classList.toggle('active', item.dataset.mmsi === String(mmsi));
  });

  const pos = livePos || state.vessels.get(mmsi)?.latestPos || state.mapManager?.getVesselData(mmsi) || {};
  const typeInfo = getShipTypeInfo(pos.shipType);

  openDetailPanel({
    title: pos.shipName ? pos.shipName.replace(/^DEMO /, '') : `Vessel ${mmsi}`,
    type: 'vessel',
  });

  renderVesselDetailSkeleton(mmsi, pos, typeInfo);

  // Fetch static vessel details (IMO, static name, created_at)
  try {
    const vesselDetail = await getVessel(mmsi);
    renderVesselDetailContent(mmsi, pos, typeInfo, vesselDetail);
  } catch (err) {
    // Graceful fallback to AIS positional data when vessel registry endpoint is not populated
    renderVesselDetailContent(mmsi, pos, typeInfo, null);
  }

  // Load and display trajectory trail
  loadVesselTrajectory(mmsi);
}

function renderVesselDetailSkeleton(mmsi, pos, typeInfo) {
  const content = dom.detailPanelContent();
  if (!content) return;

  const sog = pos.sog != null ? `${Number(pos.sog).toFixed(1)} knots` : '—';
  const cog = pos.cog != null ? `${Number(pos.cog).toFixed(1)}°` : '—';
  const heading = pos.heading != null && pos.heading >= 0 ? `${pos.heading}°` : '—';
  const coords = (pos.latitude != null && pos.longitude != null)
    ? `${pos.latitude.toFixed(5)}, ${pos.longitude.toFixed(5)}`
    : '—';

  content.innerHTML = `
    <div class="detail-section">
      <div class="detail-badge-header">
        <span class="vessel-badge large" style="background-color: ${typeInfo.color};">${typeInfo.emoji}</span>
        <div>
          <h3 class="detail-title">${escapeHtml(pos.shipName || `MMSI: ${mmsi}`)}</h3>
          <span class="detail-subtitle">${escapeHtml(typeInfo.label)}</span>
        </div>
      </div>
    </div>

    <div class="detail-section">
      <h4 class="section-heading">Telemetric Data</h4>
      <div class="detail-grid">
        <div class="detail-field">
          <span class="label">MMSI</span>
          <span class="value" id="field-vessel-mmsi">${mmsi}</span>
        </div>
        <div class="detail-field">
          <span class="label">IMO</span>
          <span class="value" id="field-vessel-imo">Loading...</span>
        </div>
        <div class="detail-field">
          <span class="label">Speed (SOG)</span>
          <span class="value" id="field-vessel-sog">${sog}</span>
        </div>
        <div class="detail-field">
          <span class="label">Course (COG)</span>
          <span class="value" id="field-vessel-cog">${cog}</span>
        </div>
        <div class="detail-field">
          <span class="label">Heading</span>
          <span class="value" id="field-vessel-heading">${heading}</span>
        </div>
        <div class="detail-field">
          <span class="label">Coordinates</span>
          <span class="value" id="field-vessel-coords">${coords}</span>
        </div>
        <div class="detail-field span-2">
          <span class="label">Last Received</span>
          <span class="value" id="field-vessel-time">${formatDate(pos.timestamp)}</span>
        </div>
      </div>
    </div>

    <div class="detail-section" id="vessel-trajectory-container">
      <h4 class="section-heading">Trajectory History</h4>
      <div class="trajectory-status text-muted">Retrieving historical positions...</div>
    </div>
  `;
}

function renderVesselDetailContent(mmsi, pos, typeInfo, vesselDetail) {
  const imoEl = document.getElementById('field-vessel-imo');
  if (imoEl) {
    imoEl.textContent = (vesselDetail && vesselDetail.imo) ? vesselDetail.imo : '—';
  }
}

function updateVesselLiveDetailFields(pos) {
  const sogEl = document.getElementById('field-vessel-sog');
  const cogEl = document.getElementById('field-vessel-cog');
  const hdgEl = document.getElementById('field-vessel-heading');
  const coordsEl = document.getElementById('field-vessel-coords');
  const timeEl = document.getElementById('field-vessel-time');

  if (sogEl && pos.sog != null) sogEl.textContent = `${Number(pos.sog).toFixed(1)} knots`;
  if (cogEl && pos.cog != null) cogEl.textContent = `${Number(pos.cog).toFixed(1)}°`;
  if (hdgEl && pos.heading != null && pos.heading >= 0) hdgEl.textContent = `${pos.heading}°`;
  if (coordsEl && pos.latitude != null && pos.longitude != null) {
    coordsEl.textContent = `${pos.latitude.toFixed(5)}, ${pos.longitude.toFixed(5)}`;
  }
  if (timeEl && pos.timestamp) {
    timeEl.textContent = formatDate(pos.timestamp);
  }
}

// ── 6. Vessel Trails & Trajectory ────────────────────────────────────────────

async function loadVesselTrajectory(mmsi) {
  const container = document.getElementById('vessel-trajectory-container');
  try {
    const data = await getVesselTrajectory(mmsi);
    if (!data || !Array.isArray(data.points) || data.points.length === 0) {
      if (container) {
        container.innerHTML = `
          <h4 class="section-heading">Trajectory History</h4>
          <div class="text-muted">No historical trajectory recorded for this vessel.</div>
        `;
      }
      return;
    }

    if (container) {
      container.innerHTML = `
        <h4 class="section-heading">Trajectory History</h4>
        <div class="trajectory-summary">
          <span>Points: <strong>${data.points.length}</strong></span>
          <span>From: ${formatDate(data.points[0]?.timestamp)}</span>
        </div>
      `;
    }
  } catch (err) {
    if (container) {
      container.innerHTML = `
        <h4 class="section-heading">Trajectory History</h4>
        <div class="text-muted">Historical trajectory query unavailable.</div>
      `;
    }
  }
}

// ── 9. Spill Selection & Candidate Vessels ──────────────────────────────────

async function selectSpill(spillId, cachedSpill = null) {
  cleanupSelection();

  state.selectedSpillId = spillId;
  state.selectedVesselMmsi = null;

  // Highlight map spill ring & pan
  state.mapManager?.selectSpill(spillId);

  // Highlight spill in sidebar
  document.querySelectorAll('.spill-item').forEach((item) => {
    item.classList.toggle('selected', item.dataset.spillId === spillId);
    item.classList.toggle('active', item.dataset.spillId === spillId);
  });

  const cached = state.spills.get(spillId);
  const spill = cached?.spill || cachedSpill;

  openDetailPanel({
    title: `Oil Spill: ${spillId}`,
    type: 'spill',
  });

  renderSpillDetailSkeleton(spillId, spill);

  // Retrieve candidate vessels if not already cached
  let candidateVessels = cached?.candidate_vessels;
  if (!candidateVessels || candidateVessels.length === 0) {
    try {
      candidateVessels = await getSpillVessels(spillId);
      if (candidateVessels && cached) {
        cached.candidate_vessels = candidateVessels;
      }
    } catch (err) {
      candidateVessels = [];
    }
  }

  renderCandidateVessels(candidateVessels);
}

function renderSpillDetailSkeleton(spillId, spill) {
  const content = dom.detailPanelContent();
  if (!content) return;

  const confPercent = spill?.confidence != null ? `${Math.round(spill.confidence * 100)}%` : '—';
  const area = spill?.area ? `${Math.round(spill.area).toLocaleString()} m²` : '—';
  const regions = spill?.region_count != null ? spill.region_count : '—';
  const crs = spill?.crs || 'EPSG:4326';
  const detectedAt = formatDate(spill?.detected_at);
  const coords = (spill?.latitude != null && spill?.longitude != null)
    ? `${spill.latitude.toFixed(5)}, ${spill.longitude.toFixed(5)}`
    : '—';

  content.innerHTML = `
    <div class="detail-section">
      <div class="detail-badge-header">
        <span class="spill-badge-icon">🛢️</span>
        <div>
          <h3 class="detail-title">Incident ${escapeHtml(spillId)}</h3>
          <span class="detail-subtitle text-danger">Confidence: ${confPercent}</span>
        </div>
      </div>
    </div>

    <div class="detail-section">
      <h4 class="section-heading">Spill Characteristics</h4>
      <div class="detail-grid">
        <div class="detail-field">
          <span class="label">Coordinates</span>
          <span class="value">${coords}</span>
        </div>
        <div class="detail-field">
          <span class="label">Estimated Area</span>
          <span class="value">${area}</span>
        </div>
        <div class="detail-field">
          <span class="label">Confidence</span>
          <span class="value">${confPercent}</span>
        </div>
        <div class="detail-field">
          <span class="label">Region Count</span>
          <span class="value">${regions}</span>
        </div>
        <div class="detail-field">
          <span class="label">CRS</span>
          <span class="value">${crs}</span>
        </div>
        <div class="detail-field">
          <span class="label">Detected At</span>
          <span class="value">${detectedAt}</span>
        </div>
      </div>
    </div>

    <div class="detail-section" id="candidate-vessels-wrapper">
      <h4 class="section-heading">Attributed Candidate Vessels</h4>
      <div id="candidate-vessels-list" class="candidate-vessels-list">
        <div class="text-muted">Loading candidate vessels...</div>
      </div>
    </div>
  `;
}

function renderCandidateVessels(candidates) {
  const list = document.getElementById('candidate-vessels-list') || dom.candidateVesselsList();
  if (!list) return;

  if (!Array.isArray(candidates) || candidates.length === 0) {
    list.innerHTML = `<div class="empty-state">No AIS candidate vessels attributed within the temporal window.</div>`;
    return;
  }

  list.innerHTML = '';

  candidates
    .slice()
    .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99))
    .forEach((cand) => {
      const card = document.createElement('div');
      card.className = 'candidate-card';

      const scorePercent = cand.attribution_score != null
        ? `${Math.round(cand.attribution_score * 100)}%`
        : '—';
      const dist = cand.distance_km != null ? `${cand.distance_km.toFixed(2)} km` : '—';
      const timeDiff = cand.time_difference_minutes != null ? `${cand.time_difference_minutes} min` : '—';

      const evidenceHtml = Array.isArray(cand.evidence) && cand.evidence.length > 0
        ? `<ul class="evidence-list">${cand.evidence.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul>`
        : '';

      card.innerHTML = `
        <div class="candidate-header">
          <span class="candidate-rank">#${cand.rank ?? 1}</span>
          <span class="candidate-name">${escapeHtml(cand.ship_name || `MMSI: ${cand.mmsi}`)}</span>
          <span class="candidate-score" title="Attribution Score">${scorePercent}</span>
        </div>
        <div class="candidate-details">
          <span>Type: ${escapeHtml(cand.ship_type || 'Unknown')}</span>
          <span>Distance: ${dist}</span>
          <span>Time Δ: ${timeDiff}</span>
        </div>
        ${evidenceHtml}
      `;

      card.addEventListener('click', () => {
        // Cross-select vessel from candidate list
        selectVessel(Number(cand.mmsi));
        showToast(`Focusing candidate #${cand.rank}: ${cand.ship_name || cand.mmsi}`, 'info', 3000);
      });

      list.appendChild(card);
    });
}

// ── 15. Detail Panel & Cleanup ───────────────────────────────────────────────

function initDetailPanel() {
  const closeBtn = dom.detailCloseBtn();
  closeBtn?.addEventListener('click', () => {
    closeDetailPanel();
    cleanupSelection();
  });
}

function openDetailPanel({ title }) {
  const panel = dom.detailPanel();
  const titleEl = dom.detailPanelTitle();

  if (titleEl && title) {
    titleEl.textContent = title;
  }

  if (panel) {
    panel.classList.remove('hidden');
    panel.classList.add('open', 'active');
  }
}

function closeDetailPanel() {
  const panel = dom.detailPanel();
  if (panel) {
    panel.classList.remove('open', 'active');
    panel.classList.add('hidden');
  }
}

function cleanupSelection() {
  state.mapManager?.deselectAllVessels();
  state.mapManager?.deselectAllSpills();

  document.querySelectorAll('.vessel-item.selected, .vessel-item.active').forEach((el) => {
    el.classList.remove('selected', 'active');
  });

  document.querySelectorAll('.spill-item.selected, .spill-item.active').forEach((el) => {
    el.classList.remove('selected', 'active');
  });
}

// ── Kickoff on DOM Loaded ───────────────────────────────────────────────────

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDashboard);
} else {
  initDashboard();
}
