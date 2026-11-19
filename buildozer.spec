[app]
title = Kazazede SOS
package.name = kazazedesos
package.domain = org.afad.acil
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 1.0
requirements = python3,kivy,pyjnius,android
orientation = portrait
fullscreen = 0
android.permissions = BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_CONNECT,BLUETOOTH_ADVERTISE,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,MODIFY_AUDIO_SETTINGS,WAKE_LOCK,POST_NOTIFICATIONS,FOREGROUND_SERVICE
android.api = 33
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a
[buildozer]
log_level = 2
warn_on_root = 1
