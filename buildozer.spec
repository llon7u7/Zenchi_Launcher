[app]
title = Zenchi
package.name = zenchi
package.domain = org.zenchi
source.dir = .
source.include_exts = py,kv,png,jpg,json
source.exclude_dirs = .venv,.venv311,__pycache__,bin,.git
version = 0.1.0
requirements = python3,kivy,kivymd,pyjnius
orientation = portrait
fullscreen = 0

android.api = 35
android.minapi = 29
android.ndk = 26b
android.ndk_api = 29
android.archs = arm64-v8a
android.accept_sdk_license = True
android.permissions = SYSTEM_ALERT_WINDOW,PACKAGE_USAGE_STATS

[buildozer]
log_level = 2
warn_on_root = 1