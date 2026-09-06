import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/alert.dart';

/// Persists alerts locally so the history list survives app restarts,
/// and stores simple app settings (backend base URL, mock mode toggle).
///
/// This is intentionally simple (SharedPreferences + JSON list) rather than
/// a full database — fine for a hackathon-scale alert list. Swap for
/// sqflite/Hive later if the history grows large.
class AlertStore {
  static const _alertsKey = 'oil_spill_alerts_v1';
  static const _baseUrlKey = 'backend_base_url';
  static const _mockModeKey = 'mock_mode_enabled';
  static const _fcmTokenKey = 'fcm_token_cached';

  static Future<List<OilSpillAlert>> loadAlerts() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getStringList(_alertsKey) ?? [];
    final alerts = raw
        .map((s) => OilSpillAlert.fromJson(jsonDecode(s) as Map<String, dynamic>))
        .toList();
    // Newest first.
    alerts.sort((a, b) => b.detectedAt.compareTo(a.detectedAt));
    return alerts;
  }

  static Future<void> saveAlerts(List<OilSpillAlert> alerts) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = alerts.map((a) => jsonEncode(a.toJson())).toList();
    await prefs.setStringList(_alertsKey, raw);
  }

  /// Adds a new alert to the front of local history, avoiding duplicates
  /// (an alert can arrive both via push and via a later history fetch).
  static Future<List<OilSpillAlert>> addAlert(OilSpillAlert alert) async {
    final existing = await loadAlerts();
    if (existing.any((a) => a.id == alert.id)) {
      return existing;
    }
    final updated = [alert, ...existing];
    await saveAlerts(updated);
    return updated;
  }

  static Future<List<OilSpillAlert>> markAllRead() async {
    final existing = await loadAlerts();
    final updated = existing.map((a) => a.copyWith(read: true)).toList();
    await saveAlerts(updated);
    return updated;
  }

  // ---- Settings ----

  static Future<String> getBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_baseUrlKey) ?? '';
  }

  static Future<void> setBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_baseUrlKey, url.trim());
  }

  static Future<bool> getMockMode() async {
    final prefs = await SharedPreferences.getInstance();
    // Default true so the app is demoable before the backend exists.
    return prefs.getBool(_mockModeKey) ?? true;
  }

  static Future<void> setMockMode(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_mockModeKey, enabled);
  }

  static Future<String?> getCachedFcmToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_fcmTokenKey);
  }

  static Future<void> setCachedFcmToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_fcmTokenKey, token);
  }
}
