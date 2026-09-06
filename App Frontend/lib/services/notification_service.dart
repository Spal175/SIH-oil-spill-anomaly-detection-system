import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import '../models/alert.dart';
import 'alert_store.dart';
import 'api_service.dart';

/// Must be a TOP-LEVEL (or static) function — this is how FCM delivers
/// data messages while the app is fully terminated or in the background.
/// Flutter re-spawns an isolate just to run this function.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  // We only persist the alert here; we do NOT show a local notification,
  // because FCM already displays a system notification for background/
  // terminated data messages IF the backend also includes a "notification"
  // block, OR we can rely on this handler + a local notification below.
  if (message.data['type'] == 'oil_spill_alert') {
    final alert = OilSpillAlert.fromFcmData(message.data);
    await AlertStore.addAlert(alert);
  }
}

class NotificationService {
  static final FlutterLocalNotificationsPlugin _localNotifications =
      FlutterLocalNotificationsPlugin();

  static const _channel = AndroidNotificationChannel(
    'oil_spill_alerts', // id
    'Oil Spill Alerts', // name
    description: 'Notifications when a new oil spill is detected',
    importance: Importance.high,
  );

  /// Call once at app startup, after Firebase.initializeApp().
  static Future<void> init({
    required void Function(OilSpillAlert alert) onAlertReceived,
  }) async {
    // --- Local notifications (for showing a banner while app is open) ---
    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    const initSettings = InitializationSettings(android: androidInit);
    await _localNotifications.initialize(settings: initSettings);
    await _localNotifications
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(_channel);

    // --- Permissions ---
    final messaging = FirebaseMessaging.instance;
    await messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );

    // --- Register background handler (terminated / background state) ---
    FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);

    // --- Foreground messages: app is open right now ---
    FirebaseMessaging.onMessage.listen((RemoteMessage message) async {
      if (message.data['type'] != 'oil_spill_alert') return;
      final alert = OilSpillAlert.fromFcmData(message.data);
      await AlertStore.addAlert(alert);
      await _showLocalNotification(alert);
      onAlertReceived(alert);
    });

    // --- User tapped a notification and the app opened from background ---
    FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
      if (message.data['type'] != 'oil_spill_alert') return;
      final alert = OilSpillAlert.fromFcmData(message.data);
      onAlertReceived(alert);
    });

    // --- App was fully terminated and opened via notification tap ---
    final initialMessage = await messaging.getInitialMessage();
    if (initialMessage != null &&
        initialMessage.data['type'] == 'oil_spill_alert') {
      final alert = OilSpillAlert.fromFcmData(initialMessage.data);
      onAlertReceived(alert);
    }

    // --- Register (and keep registering) the device token with backend ---
    final token = await messaging.getToken();
    if (token != null) {
      await AlertStore.setCachedFcmToken(token);
      await ApiService.registerDevice(token);
    }
    messaging.onTokenRefresh.listen((newToken) async {
      await AlertStore.setCachedFcmToken(newToken);
      await ApiService.registerDevice(newToken);
    });
  }

  static Future<void> _showLocalNotification(OilSpillAlert alert) async {
    final details = NotificationDetails(
      android: AndroidNotificationDetails(
        _channel.id,
        _channel.name,
        channelDescription: _channel.description,
        importance: Importance.high,
        priority: Priority.high,
      ),
    );
    await _localNotifications.show(
      id: alert.id.hashCode,
      title: 'Oil spill detected',
      body: 'Location: ${alert.latitude.toStringAsFixed(4)}, '
          '${alert.longitude.toStringAsFixed(4)}'
          '${alert.area != null ? " • ~${(alert.area! / 10000).toStringAsFixed(1)} ha" : ""}',
      notificationDetails: details,
      payload: alert.id,
    );
  }
}
