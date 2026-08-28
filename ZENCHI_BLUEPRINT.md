# Zenchi Android Launcher Blueprint

## 1. Technical requirements

### Feasibility boundary

The Kivy application can be Python-first, but two Android boundaries must be
made explicit:

- A real `AccessibilityService` is an Android `Service` declared in the
  manifest and instantiated by the framework. `pyjnius` can call an existing
  service, but cannot replace its lifecycle with a Python object.
- Android does not expose a general API for an ordinary app to throttle CPU,
  force-close arbitrary apps, or globally enable grayscale. Use a visible
  blocker screen, Usage Access, and user-configured Digital Wellbeing-style
  policies. An accessibility shim may observe the foreground window and return
  home, but it should be transparent, consent-based, and Play-policy reviewed.

Therefore the deployable design is **Python/Kivy for the app plus a minimal
Java Android shim** for the service declaration and callbacks. A strict
100%-Python APK cannot satisfy the requested native service requirement.

### Device baseline

- Android 10 (API 29) or newer; target API 35 or the current supported SDK.
- ARM64-v8a only for the first release.
- 4 GB RAM minimum, 6 GB recommended.
- 2 GB free storage minimum, including a 300-900 MB quantized model and APK
  assets. Use a 0.5B model before attempting a 1.1B model.
- Hardware-backed storage and a device with a sustained-performance profile;
  long inference sessions can heat and throttle low-end phones.

### Permissions and launcher registration

Request only the permissions needed for the selected feature set. Usage Access
and overlay access are special settings, not normal runtime permissions.

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
    <uses-permission android:name="android.permission.PACKAGE_USAGE_STATS"
        tools:ignore="ProtectedPermissions" />

    <application android:label="Zenchi" android:theme="@style/ZenchiTheme">
        <activity
            android:name="org.kivy.android.PythonActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.HOME" />
                <category android:name="android.intent.category.DEFAULT" />
            </intent-filter>
        </activity>
        <service
            android:name=".ZenchiAccessibilityService"
            android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
            android:exported="false">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data
                android:name="android.accessibilityservice"
                android:resource="@xml/accessibility_config" />
        </service>
    </application>
</manifest>
```

The manifest needs the `tools` namespace if the `tools:ignore` attribute is
kept. `BIND_ACCESSIBILITY_SERVICE` is a service protection level, not a
permission the user can grant to the Kivy process. The user must explicitly
enable the service in Settings. Open settings with:

```python
from jnius import autoclass

Settings = autoclass("android.provider.Settings")
Intent = autoclass("android.content.Intent")
PythonActivity = autoclass("org.kivy.android.PythonActivity")
PythonActivity.mActivity.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
```

### Buildozer baseline

```ini
[app]
title = Zenchi
package.name = zenchi
package.domain = org.zenchi
source.dir = .
source.include_exts = py,kv,json,gguf,png,jpg
requirements = python3,kivy,kivymd,pyjnius
orientation = portrait
android.api = 35
android.minapi = 29
android.ndk = 26b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.add_src = android_src
android.add_resources = android_res
android.permissions = SYSTEM_ALERT_WINDOW,PACKAGE_USAGE_STATS
android.gradle_dependencies =
android.presplash_color = #10161c

# Keep native compilation deterministic; do not add unsupported recipes here.
android.ndk_api = 29
android.enable_androidx = True
android.add_compile_options = -std=c++17,-O3,-fno-exceptions
```

`llama-cpp-python` is not a reliable stock Buildozer requirement. Add a
custom python-for-android recipe that builds `llama.cpp` as an ARM64 shared
library, disables CUDA/OpenCL, enables NEON, and exposes a small CFFI or JNI
surface. Pin the commit and test the recipe in a clean container. A practical
fallback is a separately built `libllama.so` plus a tiny Python bridge; do not
claim an APK is reproducible until this recipe works on CI.

## 2. Project structure

```text
zenchi/
├── main.py
├── ZENCHI_BLUEPRINT.md
├── buildozer.spec
├── android_src/org/zenchi/ZenchiAccessibilityService.java
├── android_res/xml/accessibility_config.xml
├── assets/animations/zenchi_{idle,happy,distressed,angry,thinking}.json
├── ui/
│   ├── screens.py
│   ├── widgets.py
│   └── zenchi.kv
├── bridge/
│   ├── android_services.py
│   ├── usage_stats.py
│   └── intents.py
├── engine/
│   ├── enforcer.py
│   ├── policy.py
│   └── persistence.py
├── ai/
│   ├── llm_engine.py
│   ├── prompts.py
│   └── chat_controller.py
├── mascot/
│   ├── character.py
│   ├── animations.py
│   └── states.py
└── tests/
    ├── test_policy.py
    └── test_prompts.py
```

`engine` owns decisions and remains platform-independent. `bridge` only
adapts Android APIs. UI and mascot render decisions; they never decide whether
an app is blocked. AI produces reflection text, never an unlock decision.

## 3. Critical module designs

### `bridge/android_services.py`

```python
from __future__ import annotations

from jnius import autoclass


class AndroidServices:
    def __init__(self) -> None:
        self.activity = autoclass("org.kivy.android.PythonActivity").mActivity
        self.Intent = autoclass("android.content.Intent")
        self.Uri = autoclass("android.net.Uri")

    def open_usage_access(self) -> None:
        Settings = autoclass("android.provider.Settings")
        intent = self.Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)
        self.activity.startActivity(intent)

    def open_overlay_access(self) -> None:
        Settings = autoclass("android.provider.Settings")
        intent = self.Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
        intent.setData(self.Uri.parse("package:" + str(self.activity.getPackageName())))
        self.activity.startActivity(intent)

    def go_home(self) -> None:
        intent = self.Intent(self.Intent.ACTION_MAIN)
        intent.addCategory(self.Intent.CATEGORY_HOME)
        intent.addFlags(self.Intent.FLAG_ACTIVITY_NEW_TASK)
        self.activity.startActivity(intent)
```

The Java shim receives `onAccessibilityEvent`, extracts the package name, and
sends a small event to Python through a thread-safe queue or an Android intent.
It must never silently click buttons, read password fields, or intercept
content. `UsageStatsManager.queryUsageStats` supplies aggregate usage; poll it
on a background schedule and stop polling when the app is not active.

### `engine/enforcer.py`

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    blocked: bool
    reflection_required: bool
    mascot_state: str
    reason: str


def decide(used_seconds: int, limit_seconds: int,
           package_name: str | None, reflection_complete: bool) -> Decision:
    ratio = 1.0 if limit_seconds <= 0 else used_seconds / limit_seconds
    blocked = package_name is not None or ratio >= 1.0
    reflection = blocked and not reflection_complete
    if reflection:
        return Decision(True, True, "angry", "reflection_required")
    if blocked:
        return Decision(True, False, "angry", "policy_block")
    if ratio >= 0.8:
        return Decision(False, False, "distressed", "limit_warning")
    return Decision(False, False, "idle", "within_limit")
```

Use monotonic timestamps for an active session, persist policy changes with an
atomic write, and fail closed only for the configured Zenchi blocker screen.
Do not alter device-wide performance or accessibility settings without an
explicit user action and a reversible control.

### `ai/llm_engine.py`

```python
from pathlib import Path


class ReflectionModel:
    def __init__(self, model_path: str) -> None:
        from llama_cpp import Llama
        self._llm = Llama(
            model_path=str(Path(model_path)),
            n_ctx=512,
            n_batch=32,
            n_threads=4,
            n_gpu_layers=0,
            verbose=False,
        )

    def respond(self, minutes_used: int, app_name: str) -> str:
        prompt = (
            "You are Zenchi, a concise non-judgmental reflection coach. "
            f"The user spent {minutes_used} minutes in {app_name}. "
            "Ask one honest question and offer one small next action."
        )
        result = self._llm(prompt, max_tokens=96, temperature=0.6, stop=["\n\n"])
        return result["choices"][0]["text"].strip()
```

Load the model once, serialize inference requests, cap output tokens, and
cancel inference when the screen is backgrounded. Do not send usage data to a
server. Validate model files with a checksum and keep prompts free of private
message contents.

### `mascot/character.py`

```python
from kivy.clock import Clock
from kivy.properties import StringProperty
from kivy.uix.widget import Widget


class ZenchiCharacter(Widget):
    state = StringProperty("idle")

    def set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        # The KV canvas can swap the animation source for this state.
        Clock.schedule_once(lambda _dt: self.canvas.ask_update(), 0)

    def show_reflection(self, text: str) -> None:
        self.reflection_text = text
        self.set_state("thinking")
```

Use `kivy-lottie` only if its Android packaging is verified; otherwise render
the same state files with a small Kivy `Animation`/sprite adapter. Keep the
animation manager separate from the policy and expose only the five named
states.

## 4. Mascot state matrix

| State | Asset | Trigger | Exit |
|---|---|---|---|
| `idle` | `zenchi_idle.json` | Usage below 80%; no active reflection | Warning, block, or goal completion |
| `happy` | `zenchi_happy.json` | Focus session or daily goal completed | After a short celebration, return to `idle` |
| `distressed` | `zenchi_distressed.json` | Usage reaches 80%; intensify copy at 90% | Usage drops only on a new day; otherwise block at 100% |
| `angry` | `zenchi_angry.json` | Configured app encountered or limit reached | Reflection completed, then policy permits access |
| `thinking` | `zenchi_thinking.json` | Local model is generating reflection text | Model result, timeout, or cancellation |

State changes should be event-driven and persisted so process death does not
reset a restriction. Every animation needs reduced-motion and screen-reader
accessible text alternatives.

## 5. Implementation roadmap

### Phase 1: desktop prototype

1. Keep policy decisions pure and add tests for 0%, 80%, 90%, 100%, midnight,
   restricted package, and completed reflection.
2. Build the Kivy screens: home clock, usage summary, blocker/reflection form,
   settings, and permission checklist.
3. Integrate the five mascot assets with a fake event stream. The current
   `main.py` is a dependency-light policy demonstration for this phase.

### Phase 2: Android adapters

1. Add the default-home intent filter and test changing the default launcher.
2. Add the Java accessibility shim and Settings deep links. Test explicit
   enable/disable, reboot, process death, and Android 10-15 behavior.
3. Add Usage Access aggregation and an overlay only where Android permits it.
4. Test that back, home, notifications, calls, emergency flows, and Settings
   remain recoverable. Include a visible emergency exit and uninstall path.

### Phase 3: local inference

1. Pin a Qwen 0.5B or TinyLlama GGUF and measure cold start, tokens/second,
   peak RSS, battery, and temperature on the baseline device.
2. Build and test the custom ARM64 python-for-android recipe in CI.
3. Enforce model checksum, 512-token context, short outputs, cancellation,
   and no network access from the inference process.

### Phase 4: release pipeline

1. Build `debug` and signed `release` APKs in a clean container with pinned
   SDK, NDK, Buildozer, p4a, and model commit versions.
2. Run unit tests, Python compilation, manifest inspection, and install tests
   on Android 10, 12, 14, and 15 ARM64 devices.
3. Verify launcher registration, permission recovery, accessibility policy,
   battery behavior, and a complete uninstall/reset flow.
4. Complete Play policy and privacy review before distributing an APK. A
   launcher that uses AccessibilityService must clearly disclose its purpose
   and cannot use the service for deceptive or autonomous UI manipulation.