const params = new URLSearchParams(location.search);
let API_URL = (params.get('api') || 'http://127.0.0.1:8000').replace(/\/$/, '');
let API_KNOWN = false;
const AI_HEALTH_URL = () => `${API_URL}/health`;
const WS_RECONNECT_BASE = 1000;
const WS_RECONNECT_MAX = 15000;
const TRAIL_MAX = 120;
const STALE_AFTER_MS = 30000;
const DATA_WATCHDOG_MS = 8000;

const DEFAULT_AOI = {
  north: 39.64,
  south: 37.73,
  east: -8.13,
  west: -11.45,
};

const SHIP_TYPE_RANGES = [
  { min: 20, max: 29, label: 'Sailing Vessel', color: '#22d3ee' },
  { min: 30, max: 39, label: 'Fishing Vessel', color: '#fbbf24' },
  { min: 40, max: 49, label: 'High-Speed Craft', color: '#34d399' },
  { min: 50, max: 59, label: 'Tug / Pilot', color: '#a78bfa' },
  { min: 60, max: 69, label: 'Passenger', color: '#4ade80' },
  { min: 70, max: 79, label: 'Cargo', color: '#38bdf8' },
  { min: 80, max: 89, label: 'Tanker', color: '#fb7185' },
  { min: 90, max: 99, label: 'Other', color: '#94a3b8' },
];

function shipTypeInfo(code) {
  for (const r of SHIP_TYPE_RANGES) {
    if (code !== null && code >= r.min && code <= r.max) return { label: r.label, color: r.color };
  }
  return { label: 'Unknown', color: '#94a3b8' };
}

const state = {
  ws: null,
  reconnectDelay: WS_RECONNECT_BASE,
  connected: false,
  vessels: new Map(),
  spills: new Map(),
  vesselsVisible: true,
  trailsVisible: true,
  selectedMmsi: null,
  urlIndex: 0,
  dataReceived: false,
};

const $ = (id) => document.getElementById(id);

const els = {
  wsDot: $('ws-dot'),
  wsStatusText: $('ws-status-text'),
  wsStatusPill: $('ws-status-pill'),
  apiDot: $('api-dot'),
  apiStatusText: $('api-status-text'),
  apiStatusPill: $('api-status-pill'),
  statVessels: $('stat-vessels'),
  statMsgs: $('stat-msgs'),
  vesselList: $('vessel-list'),
  vesselEmpty: $('vessel-empty'),
  vesselCountBadge: $('vessel-count-badge'),
  spillList: $('spill-list'),
  spillEmpty: $('spill-empty'),
  spillCountBadge: $('spill-count-badge'),
  statSpills: $('stat-spills'),
  btnFitBounds: $('btn-fit-bounds'),
  btnToggleTrails: $('btn-toggle-trails'),
  mapCoords: $('map-coords'),
  detailPanel: $('detail-panel'),
  panelContent: $('panel-content'),
  btnClosePanel: $('btn-close-panel'),
  toastContainer: $('toast-container'),
};

function fmtCoord(value, isLat) {
  const dir = isLat ? (value >= 0 ? 'N' : 'S') : (value >= 0 ? 'E' : 'W');
  return `${Math.abs(value).toFixed(4)} ${dir}`;
}

function toast(message, type = 'info', duration = 3600) {
  const el = document.createElement('div');
  el.className = `toast ${type === 'error' ? 'toast-error' : type === 'success' ? 'toast-success' : ''}`;
  const dot = document.createElement('span');
  dot.className = 'toast-dot';
  const text = document.createElement('span');
  text.textContent = message;
  el.append(dot, text);
  els.toastContainer.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    setTimeout(() => el.remove(), 320);
  }, duration);
}

function setWsStatus(status, text) {
  els.wsDot.className = `status-dot ${status}`;
  els.wsStatusText.textContent = text;
  els.wsStatusPill.title = `AIS stream: ${text}`;
}

function setApiStatus(status, text) {
  els.apiDot.className = `status-dot ${status}`;
  els.apiStatusText.textContent = text;
  els.apiStatusPill.title = `AI backend: ${text}`;
}

/* ---------------- Ship markers ---------------- */

function shipIcon(info) {
  const color = info.color;
  const html = `
    <div class="ship-wrap">
      <span class="ship-label">${info.name}</span>
      <div class="ship-arrow" style="color:${color}">
        <svg viewBox="0 0 28 28" fill="currentColor">
          <path d="M14 2 L21 24 L14 19.5 L7 24 Z"/>
        </svg>
      </div>
      <span class="ship-ring" style="color:${color}"></span>
    </div>`;
  return L.divIcon({
    className: 'ship-marker',
    html,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function makeVessel(mmsi) {
  const info = shipTypeInfo(null);
  const marker = L.marker([0, 0], { icon: shipIcon(info), zIndexOffset: 500, interactive: true });
  const trail = L.polyline([], {
    color: info.color,
    weight: 1.6,
    opacity: 0.5,
    dashArray: '2 5',
  });
  return {
    mmsi,
    name: `VESSEL ${mmsi}`,
    shipType: null,
    speed: null,
    course: null,
    heading: null,
    lat: null,
    lon: null,
    lastSeen: 0,
    color: info.color,
    info,
    marker,
    trail,
    clickable: true,
    staleOpacity: false,
    animFrom: null,
    animTo: null,
    animStart: 0,
    animDuration: 0,
  };
}

function shipSvgIcon(color) {
  const svg = `<svg viewBox="0 0 24 24" fill="${color}"><path d="M12 2 L20 20 L12 15.5 L4 20 Z"/></svg>`;
  return svg;
}

function avatarHtml(color) {
  return `<div class="vessel-avatar" style="color:${color}">${shipSvgIcon(color)}</div>`;
}

/* ---------------- Rendering ---------------- */

function renderVesselList() {
  const vessels = [...state.vessels.values()];
  els.vesselCountBadge.textContent = vessels.length;
  els.statVessels.textContent = vessels.length;

  els.vesselEmpty.style.display = vessels.length ? 'none' : 'flex';
  els.vesselList.innerHTML = '';

  vessels
    .sort((a, b) => a.name.localeCompare(b.name))
    .forEach((v) => renderVesselItem(v));
}

let listRenderQueued = false;
function scheduleVesselListRender() {
  if (listRenderQueued) return;
  listRenderQueued = true;
  requestAnimationFrame(() => {
    listRenderQueued = false;
    renderVesselList();
  });
}

function renderVesselItem(v) {
  const stale = Date.now() - v.lastSeen > STALE_AFTER_MS;
  const item = document.createElement('div');
  item.className = `vessel-item${v.mmsi === state.selectedMmsi ? ' selected' : ''}${stale ? ' stale' : ''}`;
  item.dataset.mmsi = v.mmsi;

  const speed = v.speed !== null ? v.speed.toFixed(1) : '—';
  item.innerHTML = `
    ${avatarHtml(v.color)}
    <div class="vessel-info">
      <div class="vessel-name">${escapeHtml(v.name)}</div>
      <div class="vessel-meta">
        <span>${v.mmsi}</span>
        <span>${Math.round(v.course ?? 0)}°</span>
      </div>
    </div>
    <div class="vessel-speed">${speed}<small> kn</small></div>`;

  item.addEventListener('click', () => selectVessel(v.mmsi));
  els.vesselList.appendChild(item);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* ---------------- Spill markers / list ---------------- */

function spillDivIcon(color, pulse = false) {
  return L.divIcon({
    className: 'spill-marker-layer',
    html: `<div class="spill-marker-icon${pulse ? ' spill-marker-pulse' : ''}" style="background:${color}"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const now = new Date();
  const diffMs = now - d.getTime();
  if (diffMs >= 0) {
    const m = Math.floor(diffMs / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
  }
  return d.toLocaleString('en-GB', { hour12: false, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function renderSpillList() {
  const spills = [...state.spills.values()];
  els.spillCountBadge.textContent = spills.length;
  els.statSpills.textContent = spills.length;

  els.spillEmpty.style.display = spills.length ? 'none' : 'flex';
  els.spillList.innerHTML = '';

  spills
    .sort((a, b) => (b.detected_at || '').localeCompare(a.detected_at || ''))
    .forEach((s) => {
      const item = document.createElement('div');
      item.className = 'spill-item';
      item.dataset.id = s.id;
      const conf = s.confidence != null ? `${(s.confidence * 100).toFixed(0)}%` : '—';
      const area = s.area != null ? `${(s.area / 1000000).toFixed(2)} km²` : '—';
      item.innerHTML = `
        <span class="spill-marker"></span>
        <div class="spill-info">
          <div class="spill-head">
            <span class="spill-name">${escapeHtml(s.candidates && s.candidates.length ? s.candidates[0].ship_name || 'Detected Spill' : 'Detected Spill')}</span>
            <span class="spill-time">${fmtTime(s.detected_at)}</span>
          </div>
          <div class="spill-meta">
            <span>${fmtCoord(s.latitude, true)}, ${fmtCoord(s.longitude, false)}</span>
            <span>${conf} conf</span>
            <span>${area}</span>
          </div>
        </div>`;
      item.addEventListener('click', () => {
        s.marker && map.panTo(s.marker.getLatLng(), { duration: 0.6 });
        s.circle && s.circle.setStyle({ color: '#f59e0b', weight: 2.5 });
        s.marker && s.marker.openPopup();
      });
      els.spillList.appendChild(item);
    });
}

function addSpill(spill, candidates = []) {
  if (!spill || spill.latitude == null || spill.longitude == null) return;
  if (state.spills.has(String(spill.id))) return false;

  const marker = L.marker([spill.latitude, spill.longitude], {
    icon: spillDivIcon('#8b5cf6', true),
    zIndexOffset: 1500,
    interactive: true,
  });

  const top = candidates[0] || {};
  const vesselLine = top.ship_name
    ? `${escapeHtml(top.ship_name)} <span class="cand-sub">(rank #${top.rank ?? 1} · ${(top.attribution_score ?? 0) * 100}% match)</span>`
    : 'No AIS vessel attributed';
  const area = spill.area != null ? `${(spill.area / 1000000).toFixed(2)} km²` : '—';
  const conf = spill.confidence != null ? `${(spill.confidence * 100).toFixed(0)}%` : '—';

  const popup = L.popup({ maxWidth: 320, className: 'spill-popup' }).setContent(
    `<div class="popup-title">🛢️ Oil Spill Detected</div>
     <div class="kv-row"><span>Location</span><b>${fmtCoord(spill.latitude, true)}, ${fmtCoord(spill.longitude, false)}</b></div>
     <div class="kv-row"><span>Detected</span><b>${fmtTime(spill.detected_at)}</b></div>
     <div class="kv-row"><span>Confidence</span><b style="color:var(--spill)">${conf}</b></div>
     <div class="kv-row"><span>Extent</span><b>${area}</b></div>
     <div class="kv-row"><span>Source vessel</span><b>${vesselLine}</b></div>
     ${candidates.length ? `<div class="popup-cands">${candidates.slice(0, 3).map((c, i) =>
       `<div class="cand-line">#${c.rank ?? i + 1} ${escapeHtml(c.ship_name || `MMSI ${c.mmsi}`)} — ${(c.distance_km ?? 0).toFixed(1)} km · ${(c.attribution_score ?? 0) * 100}%</div>`).join('')}</div>` : ''}`
  );
  marker.bindPopup(popup);

  const circle = L.circle([spill.latitude, spill.longitude], {
    radius: Math.max(1200, Math.sqrt((spill.area || 850000) / Math.PI)),
    color: '#8b5cf6',
    weight: 1.4,
    fillColor: '#8b5cf6',
    fillOpacity: 0.18,
    interactive: false,
  });

  const record = { ...spill, candidates, marker, circle };
  state.spills.set(String(spill.id), record);

  marker.addTo(map);
  circle.addTo(map);

  candidates.forEach((c, i) => {
    if (c.latitude == null || c.longitude == null) return;
    const m = L.circleMarker([c.latitude, c.longitude], {
      radius: i === 0 ? 6 : 4,
      color: '#f59e0b',
      weight: 1.4,
      fillColor: '#f59e0b',
      fillOpacity: 0.5,
      dashArray: '2 3',
    });
    m.bindTooltip(`Candidate: ${escapeHtml(c.ship_name || `MMSI ${c.mmsi}`)}`, { direction: 'top', opacity: 0.92 });
    m.addTo(map);
  });

  renderSpillList();
  toast(`Oil spill detected — ${vesselLine}`, 'success', 5200);
  return true;
}

function loadSpills() {
  fetch(`${API_URL}/oil-spills`)
    .then((res) => res.ok ? res.json() : [])
    .then((spills) => {
      if (!Array.isArray(spills)) return;
      spills.forEach((s) => addSpill(s, []));
    })
    .catch(() => {});
}

function updateTrail(v) {
  const latlngs = v.marker.getLatLng();
  v.trail.addLatLng(latlngs);
  const pts = v.trail.getLatLngs();
  if (pts.length > TRAIL_MAX) v.trail.setLatLngs(pts.slice(pts.length - TRAIL_MAX));
  v.trail.setStyle({ color: v.color, weight: 1.6, opacity: state.trailsVisible ? 0.5 : 0 });
}

function applyTrailVisibility() {
  for (const v of state.vessels.values()) {
    v.trail.setStyle({ opacity: state.trailsVisible ? 0.5 : 0 });
  }
}

function animateVessel(v) {
  const now = performance.now();
  const from = v.animFrom;
  const to = v.animTo;
  if (!from || !to || v.animDuration <= 0) return;

  let t = (now - v.animStart) / v.animDuration;
  if (t >= 1) {
    v.marker.setLatLng([to.lat, to.lon]);
    v.animFrom = null;
    v.animTo = null;
    return;
  }
  t = t < 0 ? 0 : t;
  const ease = t;
  v.marker.setLatLng([
    from.lat + (to.lat - from.lat) * ease,
    from.lon + (to.lon - from.lon) * ease,
  ]);
}

function frame() {
  for (const v of state.vessels.values()) {
    if (v.animTo) animateVessel(v);
  }
  requestAnimationFrame(frame);
}

function distanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function handlePosition(report) {
  const meta = report.MetaData || {};
  const msg = (report.Message && report.Message.PositionReport) || {};
  const lat = parseFloat(msg.Latitude ?? meta.Latitude);
  const lon = parseFloat(msg.Longitude ?? meta.Longitude);
  const mmsi = parseInt(msg.UserID ?? meta.MMSI, 10);

  if (isNaN(mmsi) || isNaN(lat) || isNaN(lon)) return;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return;

  const speed = msg.Sog !== undefined && msg.Sog !== null ? Number(msg.Sog) : null;
  const course = msg.Cog !== undefined && msg.Cog !== null ? Number(msg.Cog) : null;
  const heading = msg.TrueHeading !== undefined && msg.TrueHeading !== null ? Number(msg.TrueHeading) : null;
  const name = meta.ShipName || `VESSEL ${mmsi}`;
  const shipType = meta.ShipType !== undefined && meta.ShipType !== null ? Number(meta.ShipType) : null;

  let v = state.vessels.get(mmsi);
  const isNew = !v;

  if (isNew) {
    v = makeVessel(mmsi);
    v.marker.addTo(map);
    v.trail.addTo(map);
    v.marker.on('click', () => selectVessel(mmsi));
    v.marker.bindTooltip(name, { direction: 'top', offset: [0, -18], opacity: 0.92 });
    state.vessels.set(mmsi, v);
  }

  const info = shipTypeInfo(shipType);
  v.name = name;
  v.shipType = shipType;
  v.speed = speed;
  v.course = course;
  v.heading = heading;
  v.lastSeen = Date.now();
  v.color = info.color;

  const bearing = heading !== null && heading > 0 ? heading : (course !== null ? course : 0);
  const icon = shipIcon({ name, color: info.color });
  v.marker.setIcon(icon);

  rotateMarker(v, bearing);
  v.marker.setOpacity(1);

  if (isNew) {
    v.marker.setLatLng([lat, lon]);
    v.animFrom = null;
    v.animTo = null;
    v.lastLat = lat;
    v.lastLon = lon;
  } else {
    const cur = v.animTo ? v.animTo : { lat: v.lastLat, lon: v.lastLon };
    v.animFrom = cur;
    v.animTo = { lat, lon };
    v.animStart = performance.now();
    const dist = distanceKm(cur.lat, cur.lon, lat, lon);
    const knots = Math.max(speed || 0, 0.2);
    let dur = (dist / (knots * 1.852)) * 1000;
    dur = Math.min(3800, Math.max(1400, dur));
    v.animDuration = dur;
    v.lastLat = lat;
    v.lastLon = lon;
  }

  updateTrail(v);
  scheduleVesselListRender();
}

function rotateMarker(v, bearing) {
  const arrow = v.marker.getElement() && v.marker.getElement().querySelector('.ship-arrow');
  if (arrow) arrow.style.transform = `rotate(${bearing}deg)`;
}

function setMarkerRotation(marker, bearing) {
  const el = marker.getElement();
  if (el) {
    const arrow = el.querySelector('.ship-arrow');
    if (arrow) arrow.style.transform = `rotate(${bearing}deg)`;
  }
}

/* ---------------- Selection / detail ---------------- */

function selectVessel(mmsi) {
  state.selectedMmsi = mmsi;
  renderVesselList();
  const v = state.vessels.get(mmsi);
  if (!v) return;

  const pos = v.marker.getLatLng();
  map.panTo(pos, { duration: 0.6 });

  const info = shipTypeInfo(v.shipType);
  const bearing = v.heading !== null && v.heading > 0 ? v.heading : v.course;
  const last = new Date(v.lastSeen).toLocaleTimeString('en-GB', { hour12: false });

  els.panelContent.innerHTML = `
    <div class="panel-head">
      <div class="panel-title">${escapeHtml(v.name)}</div>
      <div class="panel-sub">MMSI ${v.mmsi} · ${info.label}</div>
    </div>
    <div class="kv-grid">
      <div class="kv"><span class="kv-label">Latitude</span><span class="kv-value">${fmtCoord(pos.lat, true)}</span></div>
      <div class="kv"><span class="kv-label">Longitude</span><span class="kv-value">${fmtCoord(pos.lng, false)}</span></div>
      <div class="kv"><span class="kv-label">Speed</span><span class="kv-value accent">${v.speed !== null ? v.speed.toFixed(1) : '—'} kn</span></div>
      <div class="kv"><span class="kv-label">Course</span><span class="kv-value">${Math.round(v.course ?? 0)}°</span></div>
      <div class="kv"><span class="kv-label">Heading</span><span class="kv-value">${Math.round(bearing ?? 0)}°</span></div>
      <div class="kv"><span class="kv-label">Ship Type</span><span class="kv-value">${info.label}</span></div>
    </div>
    <div class="section-title">Status</div>
    <div class="kv" style="grid-column: 1 / -1;">
      <span class="kv-label">Last Report</span>
      <span class="kv-value">${last}</span>
    </div>`;

  els.detailPanel.classList.add('open');
  if (v.marker.getElement()) setMarkerRotation(v.marker, bearing);
}

function closePanel() {
  els.detailPanel.classList.remove('open');
  state.selectedMmsi = null;
  renderVesselList();
}

/* ---------------- Bounds / trails ---------------- */

function aoToBounds() {
  return L.latLngBounds(
    [DEFAULT_AOI.south, DEFAULT_AOI.west],
    [DEFAULT_AOI.north, DEFAULT_AOI.east],
  );
}

function fitAll() {
  if (state.vessels.size === 0) {
    map.fitBounds(aoToBounds().pad(0.05));
    return;
  }
  const bounds = L.latLngBounds([]);
  for (const v of state.vessels.values()) {
    bounds.extend(v.marker.getLatLng());
    const pts = v.trail.getLatLngs();
    if (pts.length) for (const p of pts) bounds.extend(p);
  }
  map.fitBounds(bounds.pad(0.15), { maxZoom: 13 });
}

/* ---------------- WebSocket ---------------- */

const backendWsUrl = () => `${API_URL.replace(/^http/, 'ws')}/ws/live`;
const isBackendWs = (url) => url.endsWith('/ws/live');

const WS_FALLBACKS = [
  { url: 'ws://127.0.0.1:8001/ais', label: 'mock AIS' },
  { url: 'ws://localhost:8001/ais', label: 'mock AIS (localhost)' },
];

const wsCandidates = () => {
  const override = params.get('ws');
  if (override) return [{ url: override, label: 'custom stream' }];
  const primary = { url: backendWsUrl(), label: 'AI backend /ws/live' };
  return [primary, ...WS_FALLBACKS.filter((c) => c.url !== primary.url)];
};

function nextCandidate() {
  state.urlIndex += 1;
  if (state.urlIndex >= wsCandidates().length) {
    state.urlIndex = 0;
    setTimeout(connect, state.reconnectDelay);
  } else {
    setTimeout(connect, 300);
  }
}

function connect() {
  const list = wsCandidates();
  if (state.urlIndex >= list.length) state.urlIndex = 0;
  const { url, label } = list[state.urlIndex];
  state.dataReceived = false;
  setWsStatus('connecting', 'Connecting');

  let ws;
  try {
    ws = new WebSocket(url);
  } catch (err) {
    nextCandidate();
    return;
  }
  state.ws = ws;

  let noDataTimer = null;
  const armNoDataTimer = () => {
    clearTimeout(noDataTimer);
    noDataTimer = setTimeout(() => {
      if (!state.dataReceived && state.ws === ws && wsCandidates().length > 1 && !isBackendWs(url)) {
        console.info(`no AIS data from ${url} within ${DATA_WATCHDOG_MS}ms, trying next source`);
        ws.close();
      }
    }, DATA_WATCHDOG_MS);
  };

  ws.onopen = () => {
    state.connected = true;
    state.reconnectDelay = WS_RECONNECT_BASE;
    setWsStatus('connected', 'Live');
    if (isBackendWs(url)) setApiStatus('connected', 'Online');
    toast(`Connected to ${label} stream`, 'success', 2600);
    armNoDataTimer();
  };

  ws.onmessage = (event) => {
    state.dataReceived = true;
    clearTimeout(noDataTimer);
    recordMessage();
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    if (data && data.MessageType === 'PositionReport') {
      handlePosition(data);
    } else if (data && data.MessageType === 'SpillDetected') {
      addSpill(data.spill, data.candidate_vessels || []);
    }
  };

  ws.onclose = () => {
    clearTimeout(noDataTimer);
    state.connected = false;
    if (state.dataReceived || wsCandidates().length === 1) {
      setWsStatus('disconnected', 'Offline');
      scheduleReconnect();
    } else {
      nextCandidate();
    }
  };

  ws.onerror = () => {
    if (ws) ws.close();
  };
}

function scheduleReconnect() {
  if (state.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(state.ws.readyState)) return;
  setTimeout(connect, state.reconnectDelay);
  state.reconnectDelay = Math.min(state.reconnectDelay * 2, WS_RECONNECT_MAX);
}

/* ---------------- Heartbeat (staleness) ---------------- */

let lastStaleRender = 0;
function heartbeat() {
  const now = Date.now();
  let changed = false;
  for (const v of state.vessels.values()) {
    const stale = now - v.lastSeen > STALE_AFTER_MS;
    const el = v.marker.getElement();
    if (el) {
      const cur = el.style.opacity;
      if ((cur === '' ? 1 : parseFloat(cur)) !== (stale ? 0.35 : 1)) {
        el.style.opacity = String(stale ? 0.35 : 1);
        changed = true;
      }
    }
  }
  if (changed || now - lastStaleRender > 5000) {
    renderVesselList();
    lastStaleRender = now;
  }
}

/* ---------------- API health ---------------- */

async function discoverApi() {
  const origin = location.origin && location.origin !== 'null' ? location.origin : null;
  if (!origin) return;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(`${origin}/health`, { signal: controller.signal });
    clearTimeout(timer);
    if (res.ok) {
      API_URL = origin.replace(/\/$/, '');
      API_KNOWN = true;
    }
  } catch (err) {
    /* origin is not the AI backend; keep the static default */
  }
}

async function checkApiHealth() {
  setApiStatus('checking', 'Checking');
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${AI_HEALTH_URL()}`, { signal: controller.signal });
    clearTimeout(timer);
    if (res.ok) {
      setApiStatus('connected', 'Online');
      API_KNOWN = true;
    } else {
      setApiStatus('disconnected', 'Offline');
    }
  } catch (err) {
    setApiStatus('disconnected', 'Offline');
  }
}

/* ---------------- Message / sec meter ---------------- */

const msgTimes = [];

function meterTick() {
  const now = Date.now();
  while (msgTimes.length && now - msgTimes[0] > 1000) msgTimes.shift();
  els.statMsgs.textContent = msgTimes.length;
}

function recordMessage() {
  msgTimes.push(Date.now());
  if (msgTimes.length > 512) msgTimes.shift();
}

/* ---------------- Error surfacing ---------------- */

window.addEventListener('error', (ev) => {
  setWsStatus('error', 'Script Error');
  toast(`Frontend error: ${ev.message}`, 'error', 6000);
});

window.addEventListener('unhandledrejection', (ev) => {
  const reason = ev.reason instanceof Error ? ev.reason.message : String(ev.reason || 'unknown');
  toast(`Async error: ${reason}`, 'error', 6000);
});

/* ---------------- Init ---------------- */

const map = L.map('map', {
  center: [(DEFAULT_AOI.north + DEFAULT_AOI.south) / 2, (DEFAULT_AOI.east + DEFAULT_AOI.west) / 2],
  zoom: 9,
  zoomControl: true,
  minZoom: 5,
  maxZoom: 17,
});
L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
  {
    attribution:
      'Tiles &copy; <a href="https://developers.arcgis.com/">Esri</a> &mdash; Source: Esri',
    maxZoom: 16,
    updateWhenIdle: false,
  }
).addTo(map);

map.fitBounds(aoToBounds().pad(0.03));

els.btnFitBounds.addEventListener('click', fitAll);

els.btnToggleTrails.addEventListener('click', () => {
  state.trailsVisible = !state.trailsVisible;
  els.btnToggleTrails.classList.toggle('active', state.trailsVisible);
  applyTrailVisibility();
});

els.btnClosePanel.addEventListener('click', closePanel);

map.on('mousemove', (e) => {
  els.mapCoords.textContent = `${fmtCoord(e.latlng.lat, true)}, ${fmtCoord(e.latlng.lng, false)}`;
});

map.on('click', () => {
  if (state.selectedMmsi !== null) closePanel();
});

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && state.selectedMmsi !== null) closePanel();
});

renderVesselList();
renderSpillList();
(async () => {
  await discoverApi();
  checkApiHealth();
  connect();
  loadSpills();
})();
requestAnimationFrame(frame);
setInterval(meterTick, 250);
setInterval(checkApiHealth, 15000);
setInterval(heartbeat, 2000);
setInterval(loadSpills, 30000);