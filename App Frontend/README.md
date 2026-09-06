# Oil Spill Alert App (Flutter)

Mobile app for the SIH oil-spill anomaly detection project. It does **one job**:
notify the user the moment a new oil spill is detected, showing where it
happened. (Ship-tracking and the satellite-imagery upload dashboards live in
the separate web app your teammate is building.)

- Push notifications via Firebase Cloud Messaging (FCM) — works even when the
  app is closed/killed.
- Local alert history (list + map detail screen), stored on-device.
- **Mock mode** (on by default) — the app shows sample alerts so you can build
  and demo the UI before the backend/FCM pipeline exists. Turn it off in
  Settings once the real backend is ready.

---

## 1. What you need to run this

- Flutter SDK installed (`flutter --version` to check)
- A Firebase project (free tier is fine)
- Your teammate's backend, once it exists (see contract below)

I generated this code without a Flutter environment on my end (sandboxed, no
network), so you'll do the one-time project scaffolding + `pub get` locally.

## 2. Turn this into a runnable project

```bash
# From inside this folder:
flutter create --org com.sih --project-name oil_spill_alert_app .
```

This fills in the `android/`, `ios/`, etc. platform folders around the
`lib/` and `pubspec.yaml` I already wrote — it won't touch your existing
`lib/` files. If it asks to overwrite `pubspec.yaml`, say no (keep mine).

Then:

```bash
flutter pub get
```

## 3. Firebase setup

1. Go to https://console.firebase.google.com → create a project (or ask your
   teammate to add you to theirs — **one shared Firebase project for both the
   backend and this app** is important, since the backend sends push via the
   same project).
2. Install the FlutterFire CLI: `dart pub global activate flutterfire_cli`
3. From this project's root, run:
   ```bash
   flutterfire configure
   ```
   This overwrites `lib/firebase_options.dart` with real values and drops
   `android/app/google-services.json` in place automatically. Select the
   Android app (and iOS later if needed).
4. Apply the manifest/gradle additions in `android/MANIFEST_ADDITIONS.md`.

## 4. Run it

```bash
flutter run
```

With Mock Mode on (default), you'll immediately see 2 sample alerts. Tap one
to see the map + details screen.

## 5. Backend contract — give this to your teammate

I inspected the actual backend repo. The detection pipeline
(`POST /oil-spills/analyze`, ML → GIS → DB) already exists and already
persists spills with real fields: `id`, `latitude`, `longitude`,
`detected_at`, `confidence` (0–1), `area` (m²), and there's no
"severity" field — the app derives a high/medium/low label from
`confidence` on its own side.

Two things are genuinely missing for mobile push to work: a `GET /oil-spills`
list endpoint (only fetch-by-id exists today), and any device-registration /
push-sending code at all (there's currently zero notification
infrastructure). **See `PROPOSED_BACKEND_CHANGES.md`** in this folder for
exact, ready-to-paste code matching their existing repository/service
patterns — it's a small, additive change; nothing in the existing pipeline
needs to be touched.

Summary of the two new endpoints + push payload:

- `POST /devices/register` — `{ "token": "<fcm_token>", "platform": "android" }`
- `GET /oil-spills?since=<ISO8601>&limit=50` — array of
  `{ "id", "latitude", "longitude", "detected_at", "confidence", "area", "region_count" }`
- FCM push **data message** (not a notification message) sent right after a
  spill is saved, with the same field names as above, all as strings.

## 6. Project structure

```
lib/
  main.dart                    # app entry, wires Firebase + notifications
  firebase_options.dart        # placeholder — regenerate via flutterfire configure
  models/alert.dart            # OilSpillAlert model (parses both push data & REST JSON)
  services/
    alert_store.dart           # local persistence (SharedPreferences)
    api_service.dart           # talks to the backend (register device, fetch history)
    notification_service.dart  # FCM setup, foreground/background handlers
  screens/
    home_screen.dart           # alert list
    alert_detail_screen.dart   # map + details for one alert
    settings_screen.dart       # backend URL, mock mode toggle, shows FCM token
```

## 7. Testing push before the backend exists

Once `flutterfire configure` is done, you can test the full push pipeline
manually from the Firebase console → Cloud Messaging → "Send test message",
using the FCM token shown in the app's Settings screen — but note the
console UI only sends *notification* messages, not *data* messages, so for a
real end-to-end test you'll want your teammate's backend (or a quick
`curl`/Python script using `firebase-admin`) sending a data message as shown
above.
