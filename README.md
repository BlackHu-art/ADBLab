# ADBLab

## Overview

**ADBLab** is a PySide6 desktop GUI tool for Android device management and automated testing. It wraps ADB commands into a graphical interface supporting device connection, app management, file browsing, live logcat, screen mirroring, Monkey stress testing, and performance diagnostics.

![ADBLab UI Preview](./mge.png)

- **Language**: Python 3.11
- **GUI Framework**: PySide6 (Qt 6)
- **Author**: Frankie Hu (Copyright (c) 2026)
- **Version**: 2.8.0

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
│   ├── __init__.py                  # Composed ADBController (5 mixins)
│   ├── _base.py                     # Shared infra: models, signals, handler dispatch
│   ├── _device.py                   # Device connect, disconnect, restart, pairing
│   ├── _app.py                      # App install, uninstall, clear, permissions
│   ├── _media.py                    # Screenshot, recording, performance, battery, processes
│   └── _input.py                    # Text input, tap, swipe, keyevent, settings
│
├── models/                          # Model layer (ADB command execution)
│   ├── adb_model.py                 # @async_command decorator + ADBModelCore base
│   ├── adb_device.py                # Device connect, disconnect, restart, device info
│   ├── adb_app.py                   # App install, uninstall, clear, package/activity queries
│   ├── adb_testing.py               # Screenshot, monkey, bugreport, ANR, logs
│   ├── adb_advanced.py              # 50+ advanced operations (~900 lines)
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
│   │   ├── app_panel.py             # Tab 1 "Apps": package mgmt, monkey, testing, performance
│   │   ├── system_panel.py          # Tab 2 "System": shell, forwarding, settings, IME, emulator
│   │   ├── remote_panel.py          # Tab 3 "Remote": scrcpy mirroring, D-Pad, quick keys
│   │   └── log_panel.py             # Left-side color-coded log panel
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
│   │   ├── qss.py                   # QSS templates (buttons, inputs, group boxes, scrollbars)
│   │   ├── fonts.py                 # Font management
│   │   ├── base_styles.py           # Backward-compat re-export
│   │   └── icon_loader.py           # Theme-aware QIconEngine (SVG currentColor injection)
│   └── widgets/
│       └── double_click_button.py   # QPushButton with double-click safety guard
│
├── utils/                           # Utilities
│   ├── resource_path.py             # Resource path resolution (dev + PyInstaller)
│   └── adb_resolver.py              # ADB path resolution (bundled scrcpy/adb)
│
└── resources/                       # Static resources
    ├── connected_devices.yaml       # Device connection history
    ├── package_info.yaml            # Package name history
    ├── chkbugreport-0.5-215.jar    # Bugreport txt → html converter
    ├── app_settings.json            # App settings persistence
    ├── ZFB.jpg                      # About dialog QR code
    └── icons/                       # 1512 Phosphor Regular SVG icons
```

---

## Architecture

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
| **Handler Map** | `_ADBControllerBase._handle_async_response` | Dict dispatch for operation result types |
| **Mixin Controller** | `controllers/__init__.py` | ADBController assembled from 5 functional mixins |
| **Custom QIconEngine** | `icon_loader.py` | Theme-color injection into SVG on every paint — no widget refresh |

### Thread Model

- **Main thread**: Qt event loop + UI rendering
- **Worker threads**: `QThreadPool` (QRunnable) + `ThreadPoolExecutor(max_workers=4)`
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
| Device List | Multi-select checklist (Brand, Model, Android version, IP); select all/none |
| Device Info | 17 properties: model, brand, Android version, SDK, CPU, resolution, density, memory, storage, MAC/IP, etc. |
| Restart Device | `adb reboot` for checked devices |
| Restart ADB Server | `adb kill-server` + `adb start-server` (double-click safety) |
| Batch Install APK | Multi-file → all checked devices |
| USB Auto-Detection | 3-second `adb devices` poll, auto-refresh on device count change |
| Device Persistence | YAML store for known devices, IP history with auto-complete |

### App Management (Apps Tab)

| Feature | Description |
|---------|-------------|
| Get Foreground Package | `dumpsys window` — detect current focused app |
| Uninstall / Clear Data / Restart / Force Stop | Standard lifecycle operations |
| Disable / Enable / Disable-User | `pm disable/enable/disable-user` |
| Activity Info | Current focus and resumed activity |
| Parse APK (local) | `aapt dump badging` — label, package, version, SDK, permissions, architectures |
| Package History | Auto-complete from previously seen packages |
| Reboot Modes | System / Bootloader / Recovery / Fastboot |
| TCP/IP Mode | Enable ADB over TCP/IP on specified port |
| Email | Fetch temp email from AMZ123 API, poll for verification code |
| Input Text | `adb shell input text` to device |
| Screenshot | `screencap -p` + pull, multi-device support, opens in ScreenshotViewer |
| Screen Record | `screenrecord` with configurable duration, pull video |

### Testing & Diagnostics (Apps Tab)

| Feature | Description |
|---------|-------------|
| Monkey Test | Configurable device type (STB/Mobile), event count, throttle; auto foreground recovery; dual log capture |
| Kill Monkey | Find and kill running monkey process by PID |
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
| UI Font Size | 12 | 8–22 px (immediate apply) |
| Log Font Size | 9 | 7–16 px (immediate apply) |
| Window Size | 1200×650 | Width/height spinners |
| Panel Widths | Auto | Left/right splitter proportions |
| Confirm Dangerous Ops | On | Prompt before reboot, uninstall |
| Auto-Refresh on Connect | On | Refresh device list after connection |
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
| `auto_refresh_on_connect` | true | Auto-refresh device list |

---

## Key Features

- **USB Auto-Detection**: 3-second `adb devices` poll with automatic refresh
- **Multi-Device Support**: All operations support multiple checked devices; multi-device screenshot in a single viewer
- **1526 Icons**: Phosphor Regular SVG with theme-aware color engine
- **Dark Title Bars**: Windows native title bars follow theme via DWM API
- **scrcpy Integration**: Bundled v3.3.1 with preset profiles and FPS monitoring
- **Batch Operations**: Install APKs, uninstall apps, disable/enable — all across multiple devices
- **Live Logcat**: Combined Level+Package+Tag filter with syntax highlighting
- **App Manager**: Grid/table views, backup/restore, permission management, JSON presets
- **File Explorer**: Full-featured device file browser with chmod, text/image viewing, root mode
- **Settings Persistence**: All user preferences saved automatically with debounced writes

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
| `Build-exe.yaml` | Push to main / manual | PyInstaller `--onefile --windowed` → GitHub Release |
| `Auto-Clean.yaml` | Monthly / manual | Prune old workflow runs, keep latest 8 releases |

---

## Development

### Quick Start

```bash
pip install -r requirements.txt
python main.py
```

### Code Conventions

- All ADB operations run async — never block the main thread
- New model methods use `@async_command` decorator + `handler_map` dispatch
- Signal definitions centralized in `*_signals.py`
- All dialogs connect to `BaseStyles.theme_changed` for theme updates
- Icons use `get_themed_icon("name.svg")` (theme-aware) not raw `QIcon`
- User-facing strings in English only
