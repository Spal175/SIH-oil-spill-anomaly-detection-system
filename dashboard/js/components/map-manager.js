/**
 * map-manager.js
 * Leaflet map setup, vessel marker management, spill marker management,
 * and trail (polyline) rendering.
 *
 * AOI (from mock_ais/config.py defaults):
 *   north: 39.64, south: 37.73, east: -8.13, west: -11.45  (Portuguese Atlantic)
 */

import { getShipTypeInfo } from '../services/ais-service.js';

const AOI_BOUNDS = [[37.73, -11.45], [39.64, -8.13]];
const AOI_CENTER = [38.685, -9.79];
const AOI_ZOOM   = 7;

const MAX_TRAIL_POINTS = 12;  // positions kept per vessel trail

export class MapManager {
  constructor(containerId) {
    this._containerId = containerId;
    this._map = null;
    this._vessels = new Map();   // mmsi → { marker, trail, positions[] }
    this._spills  = new Map();   // spillId → { marker, circle }
    this._trailsVisible = true;

    // Callbacks
    this.onVesselClick = null;
    this.onSpillClick  = null;
  }

  init() {
    this._map = L.map(this._containerId, {
      center:         AOI_CENTER,
      zoom:           AOI_ZOOM,
      zoomControl:    true,
      attributionControl: true,
    });

    // CartoDB dark tiles — perfect maritime look
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20,
    }).addTo(this._map);

    // AOI bounding box
    L.rectangle(AOI_BOUNDS, {
      color:     '#00c8e8',
      weight:    1,
      opacity:   0.3,
      fillColor: '#00c8e8',
      fillOpacity: 0.03,
      dashArray: '6 4',
    }).addTo(this._map);

    // Cursor coordinates
    this._map.on('mousemove', (e) => {
      const el = document.getElementById('map-coords');
      if (el) {
        el.textContent = `${e.latlng.lat.toFixed(5)} N,  ${e.latlng.lng.toFixed(5)} E`;
      }
    });

    return this;
  }

  /** Fit map view to AOI */
  fitToAOI() {
    this._map.fitBounds(AOI_BOUNDS, { padding: [30, 30] });
  }

  /** Fit map to current vessel extents */
  fitToVessels() {
    if (this._vessels.size === 0) return this.fitToAOI();
    const latlngs = [...this._vessels.values()].map(v => v.marker.getLatLng());
    this._map.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40], maxZoom: 10 });
  }

  toggleTrails() {
    this._trailsVisible = !this._trailsVisible;
    for (const v of this._vessels.values()) {
      if (this._trailsVisible) {
        if (!this._map.hasLayer(v.trail)) v.trail.addTo(this._map);
      } else {
        if (this._map.hasLayer(v.trail)) this._map.removeLayer(v.trail);
      }
    }
    return this._trailsVisible;
  }

  // ── Vessel markers ──────────────────────────────────────────────

  /**
   * Upsert a vessel marker from a parsed AIS position.
   * @param {Object} pos - parseAISMessage() output
   */
  updateVessel(pos) {
    const { mmsi, latitude, longitude, heading, sog, shipName, shipType } = pos;
    const latlng = [latitude, longitude];
    const typeInfo = getShipTypeInfo(shipType);

    if (this._vessels.has(mmsi)) {
      const v = this._vessels.get(mmsi);
      // Smooth position update
      v.marker.setLatLng(latlng);
      v.marker.setIcon(this._vesselIcon(typeInfo, heading, shipName, false, v.selected));
      // Update trail
      v.positions.push(latlng);
      if (v.positions.length > MAX_TRAIL_POINTS) v.positions.shift();
      v.trail.setLatLngs(v.positions);
      // Store latest data
      v.latestPos = pos;
    } else {
      // Create new marker
      const icon = this._vesselIcon(typeInfo, heading, shipName, false, false);
      const marker = L.marker(latlng, { icon, zIndexOffset: 100 }).addTo(this._map);
      marker.on('click', () => this.onVesselClick?.(mmsi, pos));

      // Trail polyline
      const trail = L.polyline([[latitude, longitude]], {
        color:     typeInfo.color,
        weight:    2,
        opacity:   0.5,
        dashArray: '4 3',
      });
      if (this._trailsVisible) trail.addTo(this._map);

      this._vessels.set(mmsi, {
        marker,
        trail,
        positions: [[latitude, longitude]],
        latestPos: pos,
        selected: false,
      });
    }
  }

  selectVessel(mmsi) {
    // Deselect all
    for (const [m, v] of this._vessels) {
      v.selected = (m === mmsi);
      const typeInfo = getShipTypeInfo(v.latestPos.shipType);
      v.marker.setIcon(this._vesselIcon(typeInfo, v.latestPos.heading, v.latestPos.shipName, false, v.selected));
    }
    const v = this._vessels.get(mmsi);
    if (v) this._map.panTo(v.marker.getLatLng(), { animate: true, duration: 0.5 });
  }

  deselectVessel(mmsi) {
    const v = this._vessels.get(mmsi);
    if (!v) return;
    v.selected = false;
    const typeInfo = getShipTypeInfo(v.latestPos.shipType);
    v.marker.setIcon(this._vesselIcon(typeInfo, v.latestPos.heading, v.latestPos.shipName, false, false));
  }

  deselectAllVessels() {
    for (const [mmsi] of this._vessels) this.deselectVessel(mmsi);
  }

  getVesselData(mmsi) {
    return this._vessels.get(mmsi)?.latestPos ?? null;
  }

  getVesselCount() { return this._vessels.size; }

  _vesselIcon(typeInfo, heading, name, dimmed, selected) {
    const rotation = (heading != null && heading >= 0) ? heading : 0;
    const borderColor = selected ? '#00c8e8' : 'rgba(255,255,255,0.85)';
    const shadowCss   = selected
      ? `0 0 0 3px rgba(0,200,232,0.35), 0 0 14px rgba(0,200,232,0.4)`
      : `0 0 6px rgba(0,0,0,0.6)`;
    const scale = selected ? '1.2' : '1.0';

    const html = `
      <div style="
        position:relative;
        width:28px; height:28px;
        transform: scale(${scale});
        transform-origin: 50% 50%;
        transition: transform 0.2s;
      ">
        <!-- Heading arrow -->
        <div style="
          position:absolute;
          top:-11px; left:50%;
          transform: translateX(-50%) rotate(${rotation}deg);
          transform-origin: 50% 100%;
          width:0; height:0;
          border-left:5px solid transparent;
          border-right:5px solid transparent;
          border-bottom:10px solid ${typeInfo.color};
          opacity:0.9;
          pointer-events:none;
        "></div>
        <!-- Circle body -->
        <div style="
          width:28px; height:28px;
          border-radius:50%;
          background:${typeInfo.color};
          border:2px solid ${borderColor};
          display:flex; align-items:center; justify-content:center;
          font-size:12px;
          box-shadow: ${shadowCss};
          cursor:pointer;
          opacity:${dimmed ? 0.4 : 1};
        ">${typeInfo.emoji}</div>
        <!-- Name label -->
        <div style="
          position:absolute;
          bottom:-16px; left:50%;
          transform: translateX(-50%);
          white-space:nowrap;
          font-size:9px; font-weight:700;
          color:#fff;
          text-shadow:0 1px 4px rgba(0,0,0,0.9);
          pointer-events:none;
          letter-spacing:0.2px;
          font-family:'Inter',sans-serif;
        ">${name ? name.replace(/^DEMO /, '') : ''}</div>
      </div>
    `;

    return L.divIcon({
      html,
      className: '',
      iconSize:  [28, 28],
      iconAnchor:[14, 14],
    });
  }

  // ── Spill markers ────────────────────────────────────────────────

  /**
   * Add an oil spill marker to the map.
   * @param {Object} spill - { id, latitude, longitude, confidence, area, detected_at }
   */
  addSpill(spill) {
    if (this._spills.has(spill.id)) return; // already shown

    const latlng = [spill.latitude, spill.longitude];
    const html = `
      <div class="spill-ring" id="spill-ring-${spill.id}" title="${spill.id}">
        <div class="spill-core"></div>
      </div>
    `;
    const icon = L.divIcon({
      html,
      className: '',
      iconSize:  [44, 44],
      iconAnchor:[22, 22],
    });
    const marker = L.marker(latlng, { icon, zIndexOffset: 500 }).addTo(this._map);
    marker.on('click', () => this.onSpillClick?.(spill.id, spill));

    // Spill area circle (when area available)
    let circle = null;
    if (spill.area && spill.area > 0) {
      const radiusM = Math.sqrt(spill.area / Math.PI);
      circle = L.circle(latlng, {
        radius:      Math.max(radiusM, 500),
        color:       '#ff6b1a',
        weight:      1,
        opacity:     0.6,
        fillColor:   '#ff6b1a',
        fillOpacity: 0.08,
        dashArray:   '5 3',
      }).addTo(this._map);
    }

    this._spills.set(spill.id, { marker, circle, data: spill, selected: false });
    this._map.panTo(latlng, { animate: true, duration: 0.6 });
  }

  selectSpill(spillId) {
    for (const [id, s] of this._spills) {
      s.selected = (id === spillId);
      const ring = document.getElementById(`spill-ring-${id}`);
      if (ring) ring.classList.toggle('selected', s.selected);
    }
    const s = this._spills.get(spillId);
    if (s) this._map.panTo(s.marker.getLatLng(), { animate: true, duration: 0.5 });
  }

  deselectAllSpills() {
    for (const [id, s] of this._spills) {
      s.selected = false;
      const ring = document.getElementById(`spill-ring-${id}`);
      if (ring) ring.classList.remove('selected');
    }
  }

  getSpillCount() { return this._spills.size; }
}
