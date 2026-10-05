# Android manifest additions

After running `flutter create .` (see README §2), open
`android/app/src/main/AndroidManifest.xml` and add:

```xml
<manifest ...>
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

    <application ...>
        <!-- Default notification channel used when the app is killed -->
        <meta-data
            android:name="com.google.firebase.messaging.default_notification_channel_id"
            android:value="oil_spill_alerts" />

        <meta-data
            android:name="com.google.firebase.messaging.default_notification_icon"
            android:resource="@mipmap/ic_launcher" />
        ...
    </application>
</manifest>
```

Also add the Google Services Gradle plugin:

**`android/build.gradle` (project-level)**
```gradle
buildscript {
    dependencies {
        classpath 'com.google.gms:google-services:4.4.2'
    }
}
```

**`android/app/build.gradle` (app-level)**, add at the very bottom:
```gradle
apply plugin: 'com.google.gms.google-services'
```

And make sure `minSdkVersion` is at least 21 in `android/app/build.gradle`
(`defaultConfig { minSdkVersion 21 ... }`) — required by firebase_messaging.
