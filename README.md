# ADBLab

## Overview

**ADBLab** is a PySide6 desktop GUI tool for Android device management and automated testing. It wraps ADB commands into a graphical interface supporting device connection, app management, file browsing, live logcat, screen mirroring, Monkey stress testing, and performance diagnostics.

![ADBLab UI Preview](resources/demo.gif)

- **Language**: Python 3.11
- **GUI Framework**: PySide6 (Qt 6)
- **Author**: Frankie Hu (Copyright (c) 2026)
- **Version**: 2.9.0

---

## Directory Structure

```
ADBLab/
├── main.py                          # Entry: QApplication → MainFrame → event loop
├── requirements.txt
├── README.md
├── icon.ico
├── .gitignore
├── .github/workflows/
│   ├── Build-exe.yaml
│   └── Auto-Clean.yaml
│
├── core/                            # Core infrastructure
│   ├── adb_bridge.py                # Lightweight ADB wrapper (shell, input, dimensions)
│   ├── log_service.py               # Thread-safe singleton log service
│   ├── settings_manager.py          # App settings persistence (JSON, atomic write)
│   └── mail/
│       ├── email_service.py          # AMZ123 temp email API client
│       └── email_task.py            # QRunnable async email + verification code fetch
│
├── controllers/                     # Controller layer (mixins → ADBController)
│   ├── __init__.py                  # Composed ADBController (7 mixins)
│   ├── _base.py                     # Shared infra: models, signals, handler dispatch
│   ├── _device.py                   # Device connect, disconnect, restart, pairing
│   ├── _app.py                      # Package mgmt, app info, monkey test, bugreport, logs
│   ├── _system.py                   # Permissions, disable/enable, broadcast, activity, IME, emulator, reboot
│   ├── _media.py                    # Screenshot, recording(start/stop/auto-pull), performance, battery
│   ├── _input.py                    # Text input, tap, swipe, keyevent, settings
│   └── _file.py                     # File manager, port forwarding, content query
│
├── models/                          # Model layer (ADB command execution)
│   ├── adb_model.py                 # @async_command decorator + ADBModelCore base
│   ├── base/
│   │   ├── command_runner.py         # Unified subprocess.run entry + adb path cache
│   │   ├── process_runner.py         # Managed long-running Popen processes (monkey/logcat/etc.)
│   │   └── focus_detector.py         # Foreground package detection helper
│   ├── adb_device.py                # Device connect, disconnect, restart, device info
│   ├── adb_app.py                   # App install, uninstall, clear, package/activity queries
│   ├── adb_testing.py               # Screenshot, monkey(per-device abort), bugreport, ANR, logs
│   ├── adb_advanced.py              # Screen record(start/stop/pull), input, perf, logcat (~430 lines)
│   ├── adb_network.py               # Network ADB mixin (port forward, TCP/IP, ping)
│   ├── adb_system.py                # System ADB mixin (permissions, emulator, IME, process)
│   ├── remote/                      # Remote native services (scrcpy launch, gestures, key mapping)
│   ├── app_manager_worker.py        # App manager QThread worker (list, backup, restore)
│   ├── file_explorer_worker.py      # File explorer QThread workers (ADB shell, transfer)
│   └── device_store.py              # YAML device info persistence
│
├── gui/                             # View layer
│   ├── main_frame.py                # Frameless main window, toolbar, QSplitter, signal wiring
│   ├── panels/
│   │   ├── side_panel.py            # Right-side 3-tab container (Apps / System / Remote)
│   │   ├── side_panel_signals.py    # Signal definitions for user actions
│   │   ├── adb_control_signals.py   # Controller → UI signals
│   │   ├── base_panel.py            # Abstract panel base (UI factories, shared state)
│   │   ├── device_manager.py        # Left-side device panel (connect, list, multiselect)
│   │   ├── app_panel.py             # Tab 1 "Apps": package mgmt, monkey(configurable %), record, perf
│   │   ├── system_panel.py          # Tab 2 "System": shell, forwarding, reboot, settings, IME, emulator
│   │   ├── remote_panel.py          # Tab 3 "Remote": scrcpy mirroring, D-Pad, quick keys
│   │   └── log_panel.py             # Left-side theme-aware log, auto-scroll, batch re-render
│   ├── dialogs/
│   │   ├── about_dialog.py          # About dialog (version, QR code, copyright)
│   │   ├── screenshot_viewer.py     # Multi-image viewer (zoom, nav, copy, save, delete)
│   │   ├── app_manager.py           # App manager (list, backup, permissions, presets, batch ops)
│   │   ├── file_explorer.py         # File explorer (browse, pull, push, edit, chmod)
│   │   ├── live_logcat.py           # Live logcat (stream, filter, highlight, export)
│   │   └── settings_dialog.py       # Settings (theme, font, window/panel size, behavior)
│   ├── styles/
│   │   ├── __init__.py              # BaseStyles (ThemeMixin + QSSMixin + FontMixin)
│   │   ├── theme.py                 # Light/Dark palettes, theme switch, DWM title bar helper
│   │   ├── qss.py                   # QSS templates (buttons, inputs, group boxes, scrollbars, device list)
│   │   ├── fonts.py                 # Font management
│   │   └── icon_loader.py           # Theme-aware QIconEngine (SVG currentColor injection)
│   └── widgets/
│       └── double_click_button.py   # QPushButton with double-click safety guard
│
├── utils/                           # Utilities
│   ├── app_metadata.py              # Single app version source for UI + CI release tags
│   ├── resource_path.py             # Resource path resolution (dev + PyInstaller)
│   ├── adb_resolver.py              # ADB path resolution (bundled scrcpy/adb)
│   └── batch_tracker.py             # Multi-device batch operation progress tracker
│
├── tests/
│   └── test_model_execution.py      # Execution-layer regression tests
│
└── resources/                       # Static resources
    ├── connected_devices.yaml       # Device connection history
    ├── package_info.yaml            # Package name history
    ├── chkbugreport-0.5-215.jar    # Bugreport txt → html converter
    ├── app_settings.json            # App settings persistence
    ├── demo.gif                     # README UI preview
    ├── ZFB.jpg                      # About dialog QR code
    └── icons/                       # 1512 Phosphor Regular SVG icons
```

---

## Architecture

### 2026-05-30 Optimization Record

The latest architecture and feature-logic optimization notes are documented in:

- `docs/2026-05-30-architecture-logic-optimization.md`

This pass centralized command/process execution, tightened dialog lifecycle cleanup, made Monkey stop idempotent, added VSCode project launch configuration, and expanded regression coverage to 42 tests.

### MVC + Signal/Slot Pattern

```
User clicks button (Panel)
  → Emits signal (e.g., screenshot_requested)
  → ADBController receives, dispatches to model
  → Model executes ADB command on background thread (QRunnable)
  → Model emits command_finished signal
  → Controller processes result via handler_map dispatch
  → Emits UI signal → LogPanel / dialogs update
```

### Key Design Patterns

| Pattern | Location | Description |
|---------|----------|-------------|
| **Singleton** | `LogService`, `AppSettings` | Thread-safe singletons |
| **Observer** | Global | Qt signal/slot decoupling UI from business logic |
| **Async Command** | `adb_model.async_command` | Decorator wrapping sync methods into QRunnable async execution |
| **Command Runner** | `models/base/command_runner.py` | Single short-lived subprocess entry with adb path cache and normalized results |
| **Process Runner** | `models/base/process_runner.py` | Managed lifecycle for long-running monkey/logcat/scrcpy-like subprocesses |
| **Focus Detector** | `models/base/focus_detector.py` | Shared foreground package parser with focus-first fallback chain |
| **Handler Map** | `_ADBControllerBase._handle_async_response` | Dict dispatch for operation result types |
| **Mixin Controller** | `controllers/__init__.py` | ADBController assembled from 7 functional mixins |
| **Model Mixins** | `adb_advanced.py` | ADBAdvanced composed from ADBNetworkMixin + ADBSystemMixin |
| **Version Metadata** | `utils/app_metadata.py` | Single app version source for About dialog, Windows AppUserModelID, and CI release tags |
| **Custom QIconEngine** | `icon_loader.py` | Theme-color injection into SVG on every paint — no widget refresh |

### Thread Model

- **Main thread**: Qt event loop + UI rendering
- **Worker threads**: `QThreadPool` (QRunnable) + `ThreadPoolExecutor(max_workers=4)`
- **Long-running processes**: `ProcessRunner` owns named subprocesses and stops replaced/aborted tasks safely
- **Thread communication**: Qt cross-thread signals/slots (auto-queued)
- **Log buffering**: `LogService` uses QTimer at 200ms intervals to batch-flush

---

## GUI Layout

```
┌─ Toolbar ──────────────────────────────────────────────────┐
│ ADBLab | AppMgr | FileExpl | Logcat | Settings | CMD       │
│     [SavePath......... ] Clear | About | ☀ | ─ | ✕       │
├─ Left Column ─────┬── Right Tabs ──────────────────────────┤
│ ┌─ Devices Panel ┐│ ┌ Apps ────┬ System ───┬ Remote ─────┐ │
│ │ IP Connect     │ │ │          │           │             │ │
│ │ Device List    │ │ │          │           │             │ │
│ │ Buttons        │ │ │          │           │             │ │
│ └────────────────┘ │ └────────────────────────────────────┘ │
│ ┌─ Log Panel ────┐ │                                        │
│ │ Color-coded    │ │                                        │
│ │ Auto-scroll    │ │                                        │
│ └────────────────┘ │                                        │
└────────────────────┴────────────────────────────────────────┘
```

- **Toolbar**: App Manager, File Explorer, Live Logcat, Settings, CMD, Save Path, Clear Log, About, Theme Toggle, Minimize, Exit
- **Left column**: Device Manager (fixed height) + Log Panel (fills rest)
- **Right tabs**: Apps / System / Remote (3 tabs with scroll areas)
- **QSplitter**: Draggable divider between left and right panels

---

## Feature Catalog

### Device Management

| Feature | Description |
|---------|-------------|
| Connect / Disconnect | ADB connect/disconnect by IP:Port, history dropdown with auto-complete |
| Device List | Multi-select checklist (Brand, Model, Android version, IP); robust parser ignores adb startup banners/offline devices |
| Device Info | 17 properties: model, brand, Android version, SDK, CPU, resolution, density, memory, storage, MAC/IP, etc. |
| Restart Device | `adb reboot` for checked devices |
| Restart ADB Server | `adb kill-server` + `adb start-server` (double-click safety) |
| Batch Install APK | Multi-file → all checked devices |
| USB Auto-Detection | `_ScanThread` long-running poll every 3s, count-change auto-refresh |
| Device Persistence | YAML store for known devices, IP history with auto-complete |

### App Management (Apps Tab)

| Feature | Description |
|---------|-------------|
| Get Package | Focus-first detector (`mCurrentFocus` / `mFocusedApp`, then activity/window fallback); accumulates history |
| Uninstall / Clear Data / Restart / Force Stop | Standard lifecycle operations |
| Disable / Enable / Disable-User | `pm disable/enable/disable-user` |
| Activity Info | Current focus and resumed activity |
| Parse APK (local) | `aapt dump badging` — label, package, version, SDK, permissions, architectures |
| Package History | Auto-complete from previously seen packages |
| Email | Fetch temp email from AMZ123 API, poll for verification code |
| Input Text | `adb shell input text` to device |
| Screenshot | `screencap -p` + pull, multi-device, opens in ScreenshotViewer |
| Screen Record | Configurable duration, Record/Stop mutual exclusion, auto-pull after completion |

### Testing & Diagnostics (Apps Tab)

| Feature | Description |
|---------|-------------|
| Monkey Test | 9 configurable event-mix %, Events/Throttle/Flags, random seed, per-device abort, tiered recovery, auto-persist params |
| Kill Monkey | Stops local `ProcessRunner` monkey process and device-side monkey process with clear failure output |
| Bugreport | `adb bugreport` → extract ZIP → convert to HTML via chkbugreport |
| Pull ANR Files | `pull /data/anr` from device |
| Retrieve / Cleanup Logs | `logcat -d` to file / `logcat -c` clear buffer |
| Memory Info | `dumpsys meminfo [package]` |
| CPU Load | `dumpsys cpuinfo` |
| Battery Info | `dumpsys battery` |
| Uptime | Device uptime display |
| Top Snapshot | `top -b -n 1 -m 20` |
| GFX Info | `dumpsys gfxinfo <package> framestats` |
| Wakelocks | `cat /proc/wakelocks` |
| Net Stats | `dumpsys netstats detail` |

### System Management (System Tab)

| Feature | Description |
|---------|-------------|
| Reboot & Modes | System / Bootloader / Recovery / Fastboot + TCP/IP mode |
| Shell Command | Arbitrary `adb shell` command execution |
| Broadcast / Activity / Deep Link | `am broadcast/start` intent operations |
| Port Forward / Reverse | `adb forward/reverse` with list and remove-all |
| Service Toggles | WiFi / Data / Bluetooth / NFC ON/OFF — 8 dedicated buttons |
| Android Settings | `settings list/get/put` for system/global/secure namespaces |
| Content Query | `content query --uri` |
| Process List / Kill PID | `ps -A` / `kill <pid>` |
| Dumpsys | 16 system services pre-listed + custom input |
| Kernel / CPU Info | `cat /proc/version` / `cat /proc/cpuinfo` |
| PM Features | `pm list features` |
| Battery Simulation | Set level/status, reset to real values |
| Quick Settings | Animation disable/enable, stay awake presets |
| IME Management | List and set input methods |
| Emulator Control | SMS, call, GPS for Android emulators |

### Screen Mirroring (Remote Tab)

| Feature | Description |
|---------|-------------|
| Screen Mirroring | Bundled scrcpy v3.3.1 with full configuration |
| Video Presets | Smooth (1024@30), Balanced (1280@30), Quality (1920@60), Low Latency (720@24) |
| Custom Tuning | Resolution, FPS, codec (h264/h265/av1), buffer, bitrate, orientation lock |
| Display Options | Fullscreen, always-on-top, show touches, stay awake, turn screen off, HW encoder, no-window, no-audio |
| Recording | Record session to MP4 with auto-generated filename |
| Pre-Flight Check | USB speed test before launch |
| HW Encoder Detection | Auto-detect OMX/C2 hardware encoder |
| FPS Monitor | Live FPS from scrcpy stderr in status label |
| D-Pad | 5-key directional pad (Up/Down/Left/Right/Center) |
| Quick Keys | 16 system keys (HOME, BACK, POWER, RECENTS, etc.) |
| Keyboard Shortcuts | Ctrl+Enter start, Ctrl+Q stop |
| Settings Persistence | All video parameters saved across sessions |

Remote keeps the ADBLab UI as the user-facing shell while the implementation lives in
`models/remote/`: `ScrcpyService` owns scrcpy preflight/launch/stop behavior, and
`RemoteControlService` owns key, swipe, notification, and rotation commands. Startup reuses
the detected device dimensions for gestures, and repeated gesture taps use a short `wm size`
cache to avoid UI-thread stalls. guiscrcpy is no longer embedded or kept as a source folder.

### File Explorer

| Feature | Description |
|---------|-------------|
| Browse Filesystem | Table view (Name, Type, Size, Modified); path bar, back/forward/up navigation |
| Search / Filter | Filter files by name |
| Pull / Push | Download/upload files with progress |
| View / Edit | Text viewer (20+ formats), image viewer (png/jpg/gif/bmp) |
| File Operations | New folder, new file, rename, delete, copy/cut/paste |
| Permissions (chmod) | Interactive owner/group/other dialog with current permissions readback |
| Install APK | Direct install from device filesystem |
| Execute Script | Run shell script on device and show output |
| Properties | File/folder metadata display |
| Root Mode | Toggle `su -c` prefix for all operations |

### App Manager Dialog

| Feature | Description |
|---------|-------------|
| App List | Table view (name, package, version, status, type); grid icon view |
| Search / Filter | By text + type (All/User/System) |
| Batch Operations | Uninstall, disable, enable, backup, restore |
| Backup / Restore | Export APKs to ZIP, restore from ZIP (split APK support) |
| Presets | Save/load package selection as JSON presets |
| App Details | Tabs: app info + permissions (grant/revoke individual runtime permissions) |
| Context Menu | Launch, force stop, clear data, backup, details |

### Live Logcat

| Feature | Description |
|---------|-------------|
| Real-Time Stream | `adb logcat -v threadtime` streaming display |
| Level Filter | Verbose through Fatal (7 levels) |
| Package Filter | Auto PID lookup + `--pid` filter |
| Tag Filter | Client-side substring filter |
| Syntax Highlighting | Color-coded: V(gray) D(blue) I(green) W(orange) E(red) F(pink) |
| Operations | Start, stop, clear, export to .txt; 8000-line buffer |

### Screenshot Viewer

| Feature | Description |
|---------|-------------|
| Multi-Image Navigation | Prev/Next buttons or arrow keys; "1 / N" indicator |
| Zoom | 10%–500%, Ctrl+scroll/Ctrl+=/Ctrl+-; fit-to-window / 1:1 |
| Actions | Copy to clipboard (Ctrl+C), Save As (Ctrl+S), open folder, delete |
| Info Display | Resolution, file size, modification timestamp |
| Context Menu | All actions accessible via right-click |

### Settings Dialog

| Setting | Default | Description |
|---------|---------|-------------|
| Theme | Light | Light/Dark toggle (immediate apply) |
| Font Family | Segoe UI | 6 font choices (immediate apply) |
| UI Font Size | 12 | Dropdown: 8–22 (immediate apply) |
| Log Font Size | 9 | Dropdown: 7–16 (immediate apply) |
| Window Size | 1200×650 | Width/height number inputs |
| Panel Widths | Auto | Left/right splitter proportions |
| Save Dir | ~/ADBLab | Folder picker for default save path |
| Max Log Lines | 2000 | Log panel buffer size |
| Confirm Dangerous Ops | On | Prompt before reboot, uninstall |
| Continuous Scan | On | Poll new USB devices every 3s |
| Restore Defaults | — | Reset all settings to factory defaults |

---

## Theme System

### Light/Dark Dual Theme

- 28 color keys per theme (background, input, button, text, border, selection, scrollbar, etc.)
- One-click toggle via toolbar button
- All panels, dialogs, and widgets respond to `BaseStyles.theme_changed` signal
- **Windows title bar**: Dark/Light mode synced via `DwmSetWindowAttribute` (DWM API) — no restart needed
- Font: Segoe UI (base) + Courier New (monospace)

### Icon System

- **1512 Phosphor Regular SVG icons** replacing legacy Material icons
- **Custom QIconEngine** (`_ThemedIconEngine`): injects `currentColor` → theme `TEXT_PRIMARY` on every paint
- Theme change is instant — no widget refresh, no icon cache invalidation
- Every button and dialog window has a semantically-matched icon
- QSS icons (dropdown arrow, checkbox) inherit color via CSS

---

## Settings System

Managed by `AppSettings` singleton (`resources/app_settings.json`) with atomic write (temp file + replace) and auto-save timer:

| Setting | Default | Description |
|---------|---------|-------------|
| `theme` | Light | Current theme name |
| `font_family` | Segoe UI | UI font family |
| `ui_font_size` | 12 | UI font size (px) |
| `log_font_size` | 9 | Log panel font size (px) |
| `window_width` / `window_height` | 1200 / 650 | Window dimensions |
| `left_panel_width` | Auto-calc | Left panel width |
| `save_directory` | `~/ADBLab` | Default save path |
| `confirm_dangerous_ops` | true | Confirm before dangerous operations |
| `continuous_device_scan` | true | Continuously scan device list (every 3s) |
| `monkey_params` | see defaults | Last-used monkey test parameters (auto-persisted) |

---

## Key Features

- **Continuous Device Scan**: `_ScanThread` poll every 3s with count-change auto-refresh, toggleable in Settings
- **Multi-Device Support**: All operations support multiple checked devices; per-device monkey isolation
- **Configurable Monkey**: 9 event-mix %, Events/Throttle/Flags, random seed, auto-persist to settings
- **Smart Screen Recording**: Record/Stop mutual exclusion, auto-pull video after completion
- **1526 Icons**: Phosphor Regular SVG with theme-aware color engine
- **Dark Title Bars**: Windows native title bars follow theme via DWM API
- **scrcpy Integration**: Bundled v3.3.1 with preset profiles and FPS monitoring
- **Batch Operations**: Install APKs, uninstall apps, disable/enable — all across multiple devices
- **Live Logcat**: Combined Level+Package+Tag filter with syntax highlighting
- **Theme-Aware Logs**: Log level colors adapt to Light/Dark; smart auto-scroll pauses on manual scroll-up
- **App Manager**: Grid/table views, backup/restore, permission management, JSON presets
- **File Explorer**: Full-featured device file browser with chmod, text/image viewing, root mode
- **Settings Persistence**: All user preferences + monkey params saved automatically with debounced writes

---

## Dependencies

### Python (requirements.txt)

| Package | Version | Purpose |
|---------|---------|---------|
| PySide6 / PySide6_Essentials / PySide6_Addons | 6.8+ | Qt 6 GUI |
| PySide6_QtSvg | 6.8+ | SVG rendering (icon engine) |
| PyYAML | 6.0+ | YAML parsing |
| ruamel.yaml | latest | YAML read/write |
| Requests | 2.32+ | HTTP client (email API) |
| pyinstaller | latest | EXE packaging |

### System Requirements

- **Windows 10/11** (primary target)
- **ADB** — bundled in `scrcpy-win64-v3.3.1/`
- **aapt** — for APK parsing (external)
- **Java JRE** — for `chkbugreport-0.5-215.jar`

---

## CI/CD

| Workflow | Trigger | Action |
|----------|---------|--------|
| `Build-exe.yaml` | Push to main / manual | Read `utils.app_metadata.APP_RELEASE_TAG` → PyInstaller builds → GitHub Release |
| `Auto-Clean.yaml` | Monthly / manual | Prune old workflow runs, keep latest 8 releases |

### Versioning

`utils/app_metadata.py` is the single source of truth for application version metadata:

```python
APP_VERSION = "2.9.0"
APP_RELEASE_TAG = f"v{APP_VERSION}"
```

The same version source is used by:

- About dialog version label
- Windows `AppUserModelID` in `main.py`
- GitHub Actions artifact names
- GitHub Release tag and release title

To publish a new version, update `APP_VERSION` once, then build from `main` or run `Build-exe.yaml` manually.

---

## Development

### Quick Start

```bash
pip install -r requirements.txt
python main.py
```

### Code Conventions

- ADB operations run async via `@async_command` (QRunnable) — never block the main thread
- Short-lived commands go through `CommandRunner.run()`; long-running managed processes go through `ProcessRunner.start()`
- Fire-and-forget external launches go through `ProcessRunner.spawn()`
- UI code should not call `subprocess.run()`, `subprocess.Popen()`, or `os.startfile()` directly
- Long-running polls (device scan) use dedicated `QThread` with `msleep`-breakable loops
- Signal definitions centralized in `*_signals.py`; explicit `Qt.QueuedConnection` for cross-thread
- All dialogs connect to `BaseStyles.theme_changed` for theme updates
- All `subprocess.run` calls with `text=True` use `encoding="utf-8", errors="ignore"` (Chinese Windows compat)
- Application version changes should only update `utils/app_metadata.py`
- Icons use `get_themed_icon("name.svg")` (theme-aware) not raw `QIcon`
- Per-device state tracked with `set()` + `threading.Lock` (e.g. `_aborted_devices`, `_monkey_running`)
