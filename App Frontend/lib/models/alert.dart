import 'package:latlong2/latlong.dart';

/// Represents a single oil-spill detection alert.
///
/// Field names match the REAL backend schema (`app/schemas/oil_spill.py` →
/// `SpillDetail` / `OilSpillDetailResponse` in the FastAPI repo):
///   id, latitude, longitude, detected_at, confidence (0..1), area (m^2),
///   region_count, and (on the detail endpoint) `geometry` — a GeoJSON
///   Polygon of the actual detected spill shape, which we draw on the map
///   instead of just a pin when available.
///
/// The backend has no concept of "severity" — that's derived here on the
/// frontend from `confidence` purely for display (see [severityLabel]).
class OilSpillAlert {
  final String id;
  final DateTime detectedAt;
  final double latitude;
  final double longitude;
  final double? area; // m^2, matches backend's `area` field name
  final double? confidence; // 0..1
  final int? regionCount;
  final bool read;

  /// Outer ring of the spill's GeoJSON Polygon, as (lat, lng) points ready
  /// for `flutter_map`'s PolygonLayer. Null when the backend didn't send
  /// geometry (e.g. push payloads, or older backend versions) — the detail
  /// screen falls back to a plain marker in that case.
  final List<LatLng>? polygon;

  OilSpillAlert({
    required this.id,
    required this.detectedAt,
    required this.latitude,
    required this.longitude,
    this.area,
    this.confidence,
    this.regionCount,
    this.read = false,
    this.polygon,
  });

  /// Frontend-only severity bucket derived from confidence, since the
  /// backend doesn't send one. Adjust thresholds as your model's
  /// confidence distribution becomes clearer.
  String get severityLabel {
    final c = confidence;
    if (c == null) return 'unknown';
    if (c >= 0.8) return 'high';
    if (c >= 0.5) return 'medium';
    return 'low';
  }

  /// Parses a JSON object shaped like the backend's `SpillDetail` /
  /// `OilSpillDetailResponse` (from `GET /oil-spills/{id}`, or the proposed
  /// `GET /oil-spills` list endpoint).
  factory OilSpillAlert.fromJson(Map<String, dynamic> json) {
    return OilSpillAlert(
      id: json['id']?.toString() ?? '',
      detectedAt:
      DateTime.tryParse(json['detected_at']?.toString() ?? '') ??
          DateTime.now(),
      latitude: _toDouble(json['latitude']),
      longitude: _toDouble(json['longitude']),
      area: json['area'] != null ? _toDouble(json['area']) : null,
      confidence:
      json['confidence'] != null ? _toDouble(json['confidence']) : null,
      regionCount: json['region_count'] != null
          ? int.tryParse(json['region_count'].toString())
          : null,
      read: json['read'] == true,
      polygon: json['geometry'] != null
          ? _parseGeoJsonPolygon(json['geometry'])
          : _parseStoredPolygon(json['polygon']),
    );
  }

  /// Parses the `data` map of an FCM RemoteMessage.
  /// FCM data payloads are always Map<String, String>, so every field
  /// needs to be parsed from string. Push payloads don't carry the full
  /// geometry (too large for FCM's data payload limit) — the detail screen
  /// fetches `GET /oil-spills/{id}` if you want the polygon for a pushed
  /// alert; for now it just falls back to a marker.
  factory OilSpillAlert.fromFcmData(Map<String, dynamic> data) {
    return OilSpillAlert(
      id: data['id']?.toString() ??
          DateTime.now().millisecondsSinceEpoch.toString(),
      detectedAt:
      DateTime.tryParse(data['detected_at']?.toString() ?? '') ??
          DateTime.now(),
      latitude: _toDouble(data['latitude']),
      longitude: _toDouble(data['longitude']),
      area: data['area'] != null ? _toDouble(data['area']) : null,
      confidence:
      data['confidence'] != null ? _toDouble(data['confidence']) : null,
      regionCount: data['region_count'] != null
          ? int.tryParse(data['region_count'].toString())
          : null,
      read: false,
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'detected_at': detectedAt.toIso8601String(),
    'latitude': latitude,
    'longitude': longitude,
    'area': area,
    'confidence': confidence,
    'region_count': regionCount,
    'read': read,
    // Round-tripped in our own simple [ [lat,lng], ... ] shape for local
    // storage — see _parseStoredPolygon. Not the raw GeoJSON shape.
    if (polygon != null)
      'polygon': polygon!.map((p) => [p.latitude, p.longitude]).toList(),
  };

  OilSpillAlert copyWith({bool? read}) => OilSpillAlert(
    id: id,
    detectedAt: detectedAt,
    latitude: latitude,
    longitude: longitude,
    area: area,
    confidence: confidence,
    regionCount: regionCount,
    read: read ?? this.read,
    polygon: polygon,
  );

  static double _toDouble(dynamic v) {
    if (v == null) return 0.0;
    if (v is double) return v;
    if (v is int) return v.toDouble();
    return double.tryParse(v.toString()) ?? 0.0;
  }

  /// Parses a GeoJSON `{"type": "Polygon", "coordinates": [[[lon,lat],...]]}`
  /// (as sent by the backend's `geometry` field) into (lat,lng) points.
  /// Only the outer ring (coordinates[0]) is used — holes are ignored, which
  /// is fine for drawing a spill outline. Returns null for anything else
  /// (e.g. MultiPolygon, or missing/malformed data) rather than guessing.
  static List<LatLng>? _parseGeoJsonPolygon(dynamic geometry) {
    if (geometry is! Map) return null;
    if (geometry['type'] != 'Polygon') return null;
    final coords = geometry['coordinates'];
    if (coords is! List || coords.isEmpty) return null;
    final outerRing = coords[0];
    if (outerRing is! List) return null;
    try {
      return outerRing
          .map<LatLng>((pt) => LatLng(
        _toDouble((pt as List)[1]), // GeoJSON is [lon, lat]
        _toDouble(pt[0]),
      ))
          .toList();
    } catch (_) {
      return null;
    }
  }

  /// Parses our own local-storage round-trip shape: `[[lat,lng], ...]`.
  static List<LatLng>? _parseStoredPolygon(dynamic stored) {
    if (stored is! List || stored.isEmpty) return null;
    try {
      return stored
          .map<LatLng>((pt) => LatLng(_toDouble((pt as List)[0]), _toDouble(pt[1])))
          .toList();
    } catch (_) {
      return null;
    }
  }
}