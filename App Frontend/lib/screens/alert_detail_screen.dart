import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:intl/intl.dart';
import 'package:latlong2/latlong.dart';
import '../models/alert.dart';

class AlertDetailScreen extends StatelessWidget {
  final OilSpillAlert alert;
  const AlertDetailScreen({super.key, required this.alert});

  @override
  Widget build(BuildContext context) {
    final point = LatLng(alert.latitude, alert.longitude);
    final hasPolygon = alert.polygon != null && alert.polygon!.length >= 3;

    final initialZoom = hasPolygon ? 12.0 : 9.0;

    return Scaffold(
      appBar: AppBar(title: const Text('Spill location')),
      body: Column(
        children: [
          Expanded(
            flex: 3,
            child: FlutterMap(
              options: MapOptions(
                initialCenter: point,
                initialZoom: initialZoom,
              ),
              children: [
                TileLayer(
                  urlTemplate:
                  'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.sih.oil_spill_alert_app',
                ),
                if (hasPolygon)
                  PolygonLayer(
                    polygons: [
                      Polygon(
                        points: alert.polygon!,
                        color: Colors.red.withOpacity(0.35),
                        borderColor: Colors.red,
                        borderStrokeWidth: 2,
                      ),
                    ],
                  ),
                MarkerLayer(
                  markers: [
                    Marker(
                      point: point,
                      width: 44,
                      height: 44,
                      child: Icon(
                        hasPolygon ? Icons.circle : Icons.location_on,
                        color: Colors.red,
                        size: hasPolygon ? 14 : 44,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          Expanded(
            flex: 2,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Detected ${DateFormat('MMM d, yyyy • h:mm a').format(alert.detectedAt)}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 12),
                  _InfoRow(
                      label: 'Severity', value: alert.severityLabel.toUpperCase()),
                  if (alert.confidence != null)
                    _InfoRow(
                      label: 'Confidence',
                      value: '${(alert.confidence! * 100).toStringAsFixed(0)}%',
                    ),
                  _InfoRow(
                    label: 'Coordinates',
                    value:
                    '${alert.latitude.toStringAsFixed(5)}, ${alert.longitude.toStringAsFixed(5)}',
                  ),
                  if (alert.area != null)
                    _InfoRow(
                      label: 'Estimated area',
                      value:
                      '${(alert.area! / 10000).toStringAsFixed(2)} hectares',
                    ),
                  if (alert.regionCount != null)
                    _InfoRow(
                      label: 'Detected regions',
                      value: '${alert.regionCount}',
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;
  const _InfoRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          SizedBox(
            width: 130,
            child: Text(label, style: const TextStyle(color: Colors.grey)),
          ),
          Expanded(
            child: Text(value,
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
        ],
      ),
    );
  }
}