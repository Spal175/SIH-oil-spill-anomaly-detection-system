/**
 * ais-service.js
 * WebSocket consumer for the AI backend's live ship feed.
 * Connects to the FastAPI backend (ws://localhost:8000/ws/live), which relays
 * every PositionReport parsed and persisted by the AIS worker. The message
 * envelope is identical to the upstream AISStream.io format.
 *
 * Wire format (same as mock_ais/models.py -> back through the worker):
 * {
 *   "MessageType": "PositionReport",
 *   "MetaData": { "MMSI": int, "ShipName": str, "ShipType": int, "Latitude": float, "Longitude": float },
 *   "Message":  { "PositionReport": {
 *       "UserID": int, "Latitude": float, "Longitude": float,
 *       "Sog": float, "Cog": float, "TrueHeading": int, "Timestamp": int (epoch s)
 *   }}
 * }
 */

export const AIS_WS_URL = 'ws://localhost:8000/ws/live';

/** Ship-type codes → human label + emoji */
const SHIP_TYPE_MAP = {
  30: { label: 'Fishing',         emoji: '🎣', color: '#10b981' },
  36: { label: 'Sailing',         emoji: '⛵', color: '#a78bfa' },
  37: { label: 'Pleasure',        emoji: '🚤', color: '#f472b6' },
  40: { label: 'High-Speed',      emoji: '🚀', color: '#ef4444' },
  50: { label: 'Pilot',           emoji: '🛥️', color: '#06b6d4' },
  52: { label: 'Tug',             emoji: '🚢', color: '#8b5cf6' },
  60: { label: 'Passenger',       emoji: '🛳️', color: '#ec4899' },
  70: { label: 'Cargo',           emoji: '📦', color: '#3b82f6' },
  80: { label: 'Tanker',          emoji: '🛢️', color: '#f59e0b' },
  90: { label: 'Other',           emoji: '⚓', color: '#6b7280' },
};

export function getShipTypeInfo(code) {
  if (!code && code !== 0) return { label: 'Unknown', emoji: '⚓', color: '#6b7280' };
  // Range match
  const c = Number(code);
  for (const [key, val] of Object.entries(SHIP_TYPE_MAP)) {
    if (c === Number(key)) return val;
  }
  if (c >= 70 && c <= 79) return SHIP_TYPE_MAP[70];
  if (c >= 80 && c <= 89) return SHIP_TYPE_MAP[80];
  if (c >= 60 && c <= 69) return SHIP_TYPE_MAP[60];
  return { label: 'Other', emoji: '⚓', color: '#6b7280' };
}

/**
 * Parse a raw WebSocket message into a normalised vessel position.
 * Returns null if message cannot be parsed or is not a PositionReport.
 */
export function parseAISMessage(raw) {
  let data;
  try {
    data = typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch {
    return null;
  }
  if (!data || data.MessageType !== 'PositionReport') return null;

  const meta   = data.MetaData   || {};
  const report = (data.Message?.PositionReport) || {};

  const lat = report.Latitude  ?? meta.Latitude;
  const lon = report.Longitude ?? meta.Longitude;
  if (lat == null || lon == null) return null;

  const mmsi = report.UserID ?? meta.MMSI;
  if (!mmsi || mmsi <= 0) return null;

  const ts = report.Timestamp;
  const timestamp = typeof ts === 'number'
    ? new Date(ts * 1000)
    : new Date();

  return {
    mmsi:      Number(mmsi),
    latitude:  Number(lat),
    longitude: Number(lon),
    sog:       report.Sog        != null ? Number(report.Sog) : null,
    cog:       report.Cog        != null ? Number(report.Cog) : null,
    heading:   report.TrueHeading != null ? Number(report.TrueHeading) : null,
    shipName:  meta.ShipName  || null,
    shipType:  meta.ShipType  != null ? Number(meta.ShipType) : null,
    timestamp,
  };
}

/**
 * AISConnection — manages a WebSocket connection with exponential backoff.
 *
 * Usage:
 *   const ais = new AISConnection(url);
 *   ais.onVesselUpdate = (position) => { ... };
 *   ais.onStatusChange = (status) => { ... }; // 'connecting'|'connected'|'disconnected'|'error'
 *   ais.onStats = ({messagesPerSecond}) => { ... };
 *   ais.connect();
 */
export class AISConnection {
  constructor(url = AIS_WS_URL) {
    this.url = url;
    this._ws = null;
    this._stopped = false;
    this._reconnectDelay = 1000;
    this._reconnectMax   = 30000;
    this._msgCount       = 0;
    this._statsInterval  = null;
    this._msgInWindow    = 0;

    // Callbacks
    this.onVesselUpdate = null;
    this.onStatusChange = null;
    this.onStats        = null;
  }

  get isConnected() { return this._ws?.readyState === WebSocket.OPEN; }

  connect() {
    if (this._stopped) return;
    this._setStatus('connecting');
    try {
      this._ws = new WebSocket(this.url);
      this._ws.onopen    = () => this._onOpen();
      this._ws.onmessage = (e) => this._onMessage(e);
      this._ws.onerror   = () => this._onError();
      this._ws.onclose   = () => this._onClose();
    } catch (err) {
      this._scheduleReconnect();
    }
  }

  disconnect() {
    this._stopped = true;
    clearInterval(this._statsInterval);
    this._ws?.close();
    this._ws = null;
    this._setStatus('disconnected');
  }

  _onOpen() {
    this._reconnectDelay = 1000;
    this._setStatus('connected');
    // Stats ticker: report msgs/s every second
    this._statsInterval = setInterval(() => {
      const mps = this._msgInWindow;
      this._msgInWindow = 0;
      this.onStats?.({ messagesPerSecond: mps });
    }, 1000);
  }

  _onMessage(event) {
    this._msgCount++;
    this._msgInWindow++;
    const pos = parseAISMessage(event.data);
    if (pos) this.onVesselUpdate?.(pos);
  }

  _onError() {
    this._setStatus('error');
  }

  _onClose() {
    clearInterval(this._statsInterval);
    this._statsInterval = null;
    if (!this._stopped) {
      this._setStatus('disconnected');
      this._scheduleReconnect();
    }
  }

  _scheduleReconnect() {
    if (this._stopped) return;
    setTimeout(() => {
      if (!this._stopped) this.connect();
    }, this._reconnectDelay);
    this._reconnectDelay = Math.min(this._reconnectDelay * 2, this._reconnectMax);
  }

  _setStatus(status) {
    this.onStatusChange?.(status);
  }
}
