import 'package:flutter/material.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import '../services/alert_store.dart';
import '../services/api_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _urlController = TextEditingController();
  bool _mockMode = true;
  String? _fcmToken;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final url = await AlertStore.getBaseUrl();
    final mock = await AlertStore.getMockMode();
    final token = await AlertStore.getCachedFcmToken();
    setState(() {
      _urlController.text = url;
      _mockMode = mock;
      _fcmToken = token;
    });
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    await AlertStore.setBaseUrl(_urlController.text);
    await AlertStore.setMockMode(_mockMode);
    // Re-register the device with the (possibly new) backend URL.
    if (!_mockMode) {
      try {
        final token = _fcmToken ?? await FirebaseMessaging.instance.getToken();
        if (token != null) {
          await ApiService.registerDevice(token);
        }
      } catch (_) {
        // Push notifications not set up yet — fine for MVP, just skip.
      }
    }
    setState(() => _saving = false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Settings saved')),
      );
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SwitchListTile(
            title: const Text('Mock mode'),
            subtitle: const Text(
              'Show sample alerts instead of calling the real backend. '
              'Turn this off once your teammate\'s FastAPI + FCM pipeline is live.',
            ),
            value: _mockMode,
            onChanged: (v) => setState(() => _mockMode = v),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _urlController,
            enabled: !_mockMode,
            decoration: const InputDecoration(
              labelText: 'Backend base URL',
              hintText: 'https://your-backend.example.com',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 24),
          if (_fcmToken != null) ...[
            const Text('FCM device token (give this to backend to test push):',
                style: TextStyle(color: Colors.grey)),
            const SizedBox(height: 4),
            SelectableText(
              _fcmToken!,
              style: const TextStyle(fontSize: 12, fontFamily: 'monospace'),
            ),
            const SizedBox(height: 24),
          ],
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Save'),
          ),
        ],
      ),
    );
  }
}
