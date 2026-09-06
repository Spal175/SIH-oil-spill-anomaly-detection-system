import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';
import '../models/alert.dart';
import 'alert_store.dart';

/// ---------------------------------------------------------------------
/// BACKEND CONTRACT — see PROPOSED_BACKEND_CHANGES.md at the repo root
/// for the exact FastAPI code your teammate needs to add. Summary:
///
/// 1) POST {baseUrl}/devices/register   (NOT YET IMPLEMENTED)
///    body: { "token": "<fcm_token>", "platform": "android" }
///
/// 2) GET {baseUrl}/oil-spills?since=<iso8601>&limit=50   (NOT YET IMPLEMENTED)
///    -> JSON array shaped like the existing `SpillDetail` schema:
///    [ { "id": "...", "latitude": 12.93, "longitude": 74.82,
///        "detected_at": "2026-09-06T10:30:00Z", "confidence": 0.91,
///        "area": 152340.5, "region_count": 2 } ]
///
/// 3) FCM push data payload (backend -> FCM -> phone), sent right after
///    `OilSpillRepository.create()` succeeds inside `analyze_tiff()`:
///    { "data": { "type": "oil_spill_alert", "id": "...",
///        "latitude": "12.93", "longitude": "74.82",
///        "detected_at": "2026-09-06T10:30:00Z", "confidence": "0.91",
///        "area": "152340.5", "region_count": "2" } }
/// ---------------------------------------------------------------------
class ApiService {
  /// Sample alerts used when Mock Mode is on (Settings screen), so the UI
  /// is fully demoable before the backend/FCM pipeline is wired up.
  static final List<OilSpillAlert> _mockAlerts = [
    OilSpillAlert(
      id: 'mock-1',
      detectedAt: DateTime.now().subtract(const Duration(minutes: 12)),
      latitude: 12.9312,
      longitude: 74.8214,
      area: 152340.5,
      confidence: 0.91,
      regionCount: 2,
      polygon: const [
        LatLng(12.9350, 74.8180),
        LatLng(12.9370, 74.8230),
        LatLng(12.9330, 74.8260),
        LatLng(12.9290, 74.8225),
        LatLng(12.9300, 74.8175),
      ],
    ),
    OilSpillAlert(
      id: 'mock-2',
      detectedAt: DateTime.now().subtract(const Duration(hours: 3)),
      latitude: 15.4909,
      longitude: 73.8278,
      area: 42000.0,
      confidence: 0.63,
      regionCount: 1,
    ),
  ];

  static Future<bool> registerDevice(String fcmToken) async {
    if (await AlertStore.getMockMode()) return true;
    final baseUrl = await AlertStore.getBaseUrl();
    if (baseUrl.isEmpty) return false;
    try {
      final res = await http
          .post(
        Uri.parse('$baseUrl/devices/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'token': fcmToken, 'platform': 'android'}),
      )
          .timeout(const Duration(seconds: 10));
      return res.statusCode >= 200 && res.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  static Future<List<OilSpillAlert>> fetchAlertHistory({
    DateTime? since,
  }) async {
    if (await AlertStore.getMockMode()) {
      return _mockAlerts;
    }
    final baseUrl = await AlertStore.getBaseUrl();
    if (baseUrl.isEmpty) return [];
    try {
      final uri = Uri.parse('$baseUrl/oil-spills').replace(
        queryParameters:
        since != null ? {'since': since.toIso8601String()} : null,
      );
      final res = await http.get(uri).timeout(const Duration(seconds: 10));
      if (res.statusCode != 200) return [];
      final List<dynamic> body = jsonDecode(res.body);
      return body
          .map((e) => OilSpillAlert.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (_) {
      return [];
    }
  }
}