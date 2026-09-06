import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../models/alert.dart';
import '../services/alert_store.dart';
import '../services/api_service.dart';
import 'alert_detail_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => HomeScreenState();
}

class HomeScreenState extends State<HomeScreen> {
  List<OilSpillAlert> _alerts = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadAlerts();
  }

  Future<void> _loadAlerts() async {
    setState(() => _loading = true);
    final local = await AlertStore.loadAlerts();
    setState(() {
      _alerts = local;
      _loading = false;
    });
    final remote = await ApiService.fetchAlertHistory();
    for (final a in remote) {
      await AlertStore.addAlert(a);
    }
    if (remote.isNotEmpty) {
      final refreshed = await AlertStore.loadAlerts();
      if (mounted) setState(() => _alerts = refreshed);
    }
  }

  void addAlertToTop(OilSpillAlert alert) {
    setState(() {
      _alerts = [alert, ..._alerts.where((a) => a.id != alert.id)];
    });
  }

  _SeverityStyle _severityStyle(String severity) {
    switch (severity.toLowerCase()) {
      case 'high':
        return _SeverityStyle(
          color: const Color(0xFFDC2626),
          bg: const Color(0xFFFEE2E2),
          icon: Icons.priority_high_rounded,
        );
      case 'medium':
        return _SeverityStyle(
          color: const Color(0xFFD97706),
          bg: const Color(0xFFFEF3C7),
          icon: Icons.warning_rounded,
        );
      case 'low':
        return _SeverityStyle(
          color: const Color(0xFF2563EB),
          bg: const Color(0xFFDBEAFE),
          icon: Icons.info_rounded,
        );
      default:
        return _SeverityStyle(
          color: Colors.blueGrey,
          bg: Colors.blueGrey.withOpacity(0.12),
          icon: Icons.water_drop_rounded,
        );
    }
  }

  String _relativeTime(DateTime time) {
    final diff = DateTime.now().difference(time);
    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    return DateFormat('MMM d').format(time);
  }

  int get _unreadCount => _alerts.where((a) => !a.read).length;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF4F6F8),
      body: CustomScrollView(
        slivers: [
          SliverAppBar(
            pinned: true,
            expandedHeight: 116,
            backgroundColor: const Color(0xFF0B5D8C),
            foregroundColor: Colors.white,
            actions: [
              IconButton(
                icon: const Icon(Icons.settings_outlined),
                onPressed: () async {
                  await Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const SettingsScreen()),
                  );
                  _loadAlerts();
                },
              ),
              const SizedBox(width: 4),
            ],
            flexibleSpace: FlexibleSpaceBar(
              titlePadding: const EdgeInsets.only(left: 20, bottom: 16),
              title: const Text(
                'Oil Spill Alerts',
                style: TextStyle(fontWeight: FontWeight.w700, fontSize: 20),
              ),
              background: Container(
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [Color(0xFF0B5D8C), Color(0xFF14A0C4)],
                  ),
                ),
                child: Align(
                  alignment: Alignment.bottomRight,
                  child: Padding(
                    padding: const EdgeInsets.only(right: 20, bottom: 16),
                    child: _unreadCount > 0
                        ? Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.white.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        '$_unreadCount new',
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                            fontWeight: FontWeight.w600),
                      ),
                    )
                        : const SizedBox.shrink(),
                  ),
                ),
              ),
            ),
          ),
          if (_loading)
            const SliverFillRemaining(
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_alerts.isEmpty)
            SliverFillRemaining(child: _EmptyState(onRefresh: _loadAlerts))
          else
            SliverToBoxAdapter(
              child: RefreshIndicator(
                onRefresh: _loadAlerts,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
                  child: Column(
                    children: _alerts.map((alert) {
                      final style = _severityStyle(alert.severityLabel);
                      return Container(
                        margin: const EdgeInsets.only(bottom: 12),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(16),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withOpacity(0.04),
                              blurRadius: 10,
                              offset: const Offset(0, 3),
                            ),
                          ],
                        ),
                        child: Material(
                          color: Colors.transparent,
                          borderRadius: BorderRadius.circular(16),
                          clipBehavior: Clip.antiAlias,
                          child: InkWell(
                            onTap: () {
                              Navigator.push(
                                context,
                                MaterialPageRoute(
                                  builder: (_) =>
                                      AlertDetailScreen(alert: alert),
                                ),
                              );
                            },
                            child: Padding(
                              padding: const EdgeInsets.all(14),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Container(
                                    width: 44,
                                    height: 44,
                                    decoration: BoxDecoration(
                                      color: style.bg,
                                      shape: BoxShape.circle,
                                    ),
                                    child: Icon(style.icon,
                                        color: style.color, size: 22),
                                  ),
                                  const SizedBox(width: 12),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                      children: [
                                        Row(
                                          children: [
                                            Container(
                                              padding:
                                              const EdgeInsets.symmetric(
                                                  horizontal: 8,
                                                  vertical: 2),
                                              decoration: BoxDecoration(
                                                color: style.bg,
                                                borderRadius:
                                                BorderRadius.circular(6),
                                              ),
                                              child: Text(
                                                alert.severityLabel
                                                    .toUpperCase(),
                                                style: TextStyle(
                                                  color: style.color,
                                                  fontSize: 11,
                                                  fontWeight: FontWeight.w700,
                                                  letterSpacing: 0.3,
                                                ),
                                              ),
                                            ),
                                            const Spacer(),
                                            Text(
                                              _relativeTime(alert.detectedAt),
                                              style: TextStyle(
                                                color: Colors.grey.shade500,
                                                fontSize: 12,
                                              ),
                                            ),
                                          ],
                                        ),
                                        const SizedBox(height: 8),
                                        Text(
                                          'Oil spill detected',
                                          style: TextStyle(
                                            fontSize: 15,
                                            fontWeight: alert.read
                                                ? FontWeight.w500
                                                : FontWeight.w700,
                                            color: const Color(0xFF1F2937),
                                          ),
                                        ),
                                        const SizedBox(height: 4),
                                        Row(
                                          children: [
                                            Icon(Icons.location_on_outlined,
                                                size: 14,
                                                color: Colors.grey.shade500),
                                            const SizedBox(width: 4),
                                            Expanded(
                                              child: Text(
                                                '${alert.latitude.toStringAsFixed(4)}, '
                                                    '${alert.longitude.toStringAsFixed(4)}',
                                                style: TextStyle(
                                                  color: Colors.grey.shade600,
                                                  fontSize: 13,
                                                ),
                                                overflow:
                                                TextOverflow.ellipsis,
                                              ),
                                            ),
                                          ],
                                        ),
                                        if (alert.area != null) ...[
                                          const SizedBox(height: 2),
                                          Text(
                                            '~${(alert.area! / 10000).toStringAsFixed(1)} hectares'
                                                '${alert.regionCount != null ? " • ${alert.regionCount} region(s)" : ""}',
                                            style: TextStyle(
                                              color: Colors.grey.shade500,
                                              fontSize: 12,
                                            ),
                                          ),
                                        ],
                                      ],
                                    ),
                                  ),
                                  if (!alert.read)
                                    Container(
                                      margin: const EdgeInsets.only(
                                          left: 8, top: 4),
                                      width: 8,
                                      height: 8,
                                      decoration: const BoxDecoration(
                                        color: Color(0xFF14A0C4),
                                        shape: BoxShape.circle,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _SeverityStyle {
  final Color color;
  final Color bg;
  final IconData icon;
  _SeverityStyle({required this.color, required this.bg, required this.icon});
}

class _EmptyState extends StatelessWidget {
  final Future<void> Function() onRefresh;
  const _EmptyState({required this.onRefresh});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 88,
            height: 88,
            decoration: BoxDecoration(
              color: const Color(0xFFD1FAE5),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.check_circle_rounded,
                size: 44, color: Color(0xFF059669)),
          ),
          const SizedBox(height: 20),
          const Text(
            'No oil spill alerts yet',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 40),
            child: Text(
              'You\'ll be notified here the moment one is detected.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey.shade500),
            ),
          ),
          const SizedBox(height: 20),
          TextButton.icon(
            onPressed: onRefresh,
            icon: const Icon(Icons.refresh),
            label: const Text('Refresh'),
          ),
        ],
      ),
    );
  }
}