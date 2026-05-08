# ADBLab

## Overview

**ADBLab** is a PySide6 desktop GUI tool for Android device management and automated testing. It wraps ADB commands into a graphical interface supporting device connection, app management, file browsing, live logcat, Monkey stress testing, and bugreport capture/analysis.

![ADBLab UI Preview](./mge.png)

- **Language**: Python 3.11
- **GUI Framework**: PySide6 (Qt 6)
- **Author**: Frankie Hu (Copyright (c) 2025.4)
- **Version**: 2.8.0

---

## Directory Structure

```
ADBLab/
├── main.py                          # Entry: QApplication → MainFrame → event loop
├── requirements.txt                 # Python dependencies
├── README.md
├── icon.ico                         # App icon (for Windows EXE)
├── .gitignore
├── .github/workflows/
│   ├── Build-exe.yaml               # PyInstaller EXE build + GitHub Release
│   └── Auto-Clean.yaml              # Scheduled cleanup of old builds/releases
│
├── core/                            # Core infrastructure
│   ├── log_service.py               # Thread-safe singleton log service (QTimer buffer → signal → GUI)
│   ├── settings_manager.py          # App settings persistence (JSON singleton, atomic write)
│   ├── logger/                      # loguru-based logger (unused by active codebase)
│   │   ├── log.ini
│   │   └── log_tool.py
│   └── mail/                        # Temporary email service
│       ├── email_service.py          # AMZ123 temp email API client
│       └── email_task.py            # QRunnable async email + verification code fetch
│
├── controllers/                     # Controller layer (mixins assembled into ADBController)
│   ├── __init__.py                  # Composed ADBController class (5 mixins)
│   ├── _base.py                     # Shared infrastructure: models, signals, handler dispatch, ThreadPoolExecutor
│   ├── _device.py                   # Device connection, disconnect, restart, reboot, pairing
│   ├── _app.py                      # App install, uninstall, clear, permissions, broadcast, activity, deeplink
│   ├── _input.py                    # Text input, tap, swipe, keyevent, settings
│   ├── _file.py                     # File list, push, pull, shell, port forwarding
│   └── _media.py                    # Screenshots, screen recording, performance, battery, processes
│
├── models/                          # Model layer (data + ADB command execution)
│   ├── adb_model.py                 # Core: @async_command decorator + ADBModelCore base class
│   ├── adb_device.py                # Device mgmt: connect, disconnect, restart, device info
│   ├── adb_app.py                   # App mgmt: install, uninstall, clear, package/activity queries
│   ├── adb_testing.py               # Testing: screenshot, monkey, bugreport, ANR, logs, dumpsys
│   ├── adb_advanced.py              # Advanced: recording, input, port forward, settings, shell, file, permissions, broadcasts, pairing, processes, content provider, battery, IME, emulator (~900 lines)
│   └── device_store.py              # Thread-safe YAML device info persistence
│
├── gui/                             # View layer
│   ├── main_frame.py                # Main window: frameless, toolbar, QSplitter left/right, signal wiring
│   ├── panels/
│   │   ├── side_panel.py            # Right-side 4-tab container (Apps / Testing / System / Remote)
│   │   ├── side_panel_signals.py    # 50+ signal definitions for all user actions
│   │   ├── adb_control_signals.py   # 8 ADBController → UI signals
│   │   ├── base_panel.py            # Abstract tab base: UI factories (_g, _b, _in, _combo), shared state access
│   │   ├── device_manager.py        # Left-side device panel: connect, device list, text input, screenshots
│   │   ├── app_panel.py             # Tab 1 "Apps": package selector, lifecycle, permissions, broadcast, intents
│   │   ├── testing_panel.py         # Tab 2 "Testing": reboot modes, monkey, reports, performance, logcat, input
│   │   ├── system_panel.py          # Tab 3 "System": shell, port forwarding, service toggles, settings, tools, battery, IME, emulator
│   │   ├── remote_panel.py          # Tab 4 "Remote": scrcpy mirroring, D-Pad, keys, gestures, capture
│   │   └── log_panel.py             # Left-side color-coded log panel (6 levels, auto-scroll, re-render on theme)
│   ├── dialogs/
│   │   ├── about_dialog.py          # About dialog (frameless, drag-to-move)
│   │   ├── screenshot_viewer.py     # Screenshot viewer (frameless, zoom, navigation, pin toggle)
│   │   ├── app_manager.py           # App manager (list, backup, permissions, presets, batch ops)
│   │   ├── file_explorer.py         # File explorer (browse, pull, push, edit, permissions, chmod)
│   │   ├── live_logcat.py           # Live logcat viewer (streaming, filter, color highlight, export)
│   │   └── settings_dialog.py       # Settings dialog (theme, font, window/panel size, save path, behavior)
│   ├── styles/
│   │   └── base_styles.py           # Theme system (Light/Dark dual theme, QSS templates, fonts, ThemeSignal)
│   └── widgets/
│       └── double_click_button.py   # QPushButton with double-click signal (safety guard)
│
├── utils/                           # Utilities
│   ├── resource_path.py             # Resource path resolution (dev + PyInstaller bundled)
│   └── batch_tracker.py            # Batch operation progress tracker (N/Total + summary)
│
└── resources/                       # Static resources
    ├── connected_devices.yaml       # Device connection history
    ├── package_info.yaml            # Package name history
    ├── chkbugreport-0.5-215.jar    # Bugreport txt→html converter
    ├── app_settings.json            # App settings persistence
    └── icons/                       # SVG vector icons
```

---

## Architecture

### MVC + Signal/Slot Pattern

```
User clicks button (SidePanel tab)
  → SidePanel emits signal (e.g., connect_requested)
  → ADBController receives, dispatches to model
  → Model executes ADB command on background thread (QRunnable)
  → Model emits command_finished signal
  → ADBController processes result via handler_map dispatch
  → Emits UI signal → LogPanel / SidePanel updates display
```

### Key Design Patterns

| Pattern | Location | Description |
|---------|----------|-------------|
| **Singleton** | `LogService`, `AppSettings` | Thread-safe singletons with `__new__` + mutex |
| **Observer** | Global | Qt signal/slot decoupling UI from business logic |
| **Async Command** | `adb_model.async_command` | Decorator wrapping sync methods into QRunnable async execution |
| **Handler Map** | `_ADBControllerBase._handle_async_response` | Dict dispatch for 70+ operation result types |
| **Mixin Controller** | `controllers/__init__.py` | ADBController assembled from 5 functional mixins + base |
| **Batch Tracker** | `batch_tracker.py` | Multi-device operation progress (N/Total) with summary callback |

### Thread Model

- **Main thread**: Qt event loop + UI rendering
- **Worker threads**: `QThreadPool` (QRunnable) + `ThreadPoolExecutor(max_workers=4)`, all ADB commands execute off-main-thread
- **Thread communication**: Qt cross-thread signals/slots (auto-queued)
- **Log buffering**: `LogService` uses QTimer at 200ms intervals to batch-flush to GUI

---

## GUI Layout

Main window: top toolbar + left/right split panels (QSplitter, draggable divider):

```
┌─ Toolbar ───────────────────────────────────────────────┐
│ ADBLab | AppMgr | FileExpl | Logcat | Settings | CMD    │
│                              Clear | About | ☀ | ─ | ✕ │
├─ Left Column ──────┬── Right Tabs ─────────────────────┤
│ ┌─ Devices Panel ┐ │ ┌ Apps ─┬ Testing ─┬ System ─┬ Remote ─┐ │
│ │ IP Connect     │ │ │       │          │         │         │ │
│ │ Device List    │ │ │       │          │         │         │ │
│ │ Buttons        │ │ │       │          │         │         │ │
│ └────────────────┘ │ └──────────────────────────────────────┘ │
│ ┌─ Log Panel ────┐ │                                          │
│ │ Color logs     │ │                                          │
│ │ Auto-scroll    │ │                                          │
│ └────────────────┘ │                                          │
└────────────────────┴──────────────────────────────────────────┘
```

- **Left column**: Device Manager (fixed height) + Log Panel (fills remaining space)
- **Right tabs**: Apps / Testing / System / Remote (4 tabs with scroll areas)
- **QSplitter**: Draggable 5px handle between left and right, left panel fixed width, right panel stretches with window
- **Window**: Frameless with toolbar drag-to-move, fixed default size (1200×650), adjustable via Settings

---

## Tab Details

### Tab 1: Apps

| Feature | ADB Command |
|---------|-------------|
| Get foreground app | `adb shell dumpsys window` |
| Uninstall app | `adb uninstall` |
| Clear data | `adb shell pm clear` |
| Restart app | `am force-stop` → `monkey -p <pkg> 1` |
| Activity info | `dumpsys window` + `dumpsys activity activities` |
| Force stop | `am force-stop` |
| Parse APK info | `aapt dump badging` (external tool) |
| PM Path / PM Dump | `pm path <pkg>` / `pm dump <pkg>` |
| 3rd Party / System packages | `pm list packages -3 / -s` |
| Grant / Revoke permissions | `pm grant / pm revoke` |
| List permissions | `pm dump <pkg>` |
| Disable / Enable app | `pm disable / pm enable / pm disable-user` |
| Send broadcast | `am broadcast -a <action>` |
| Start activity | `am start -n <component>` |
| Open deep link | `am start -d <uri>` |

### Tab 2: Testing

| Feature | ADB Command |
|---------|-------------|
| Reboot modes | `adb reboot <mode>` |
| TCP/IP mode | `adb tcpip <port>` |
| Monkey test | `adb shell monkey` + synced logcat + auto-foreground restore |
| Kill monkey | `ps \| grep monkey` → `kill <pid>` |
| List packages | `pm list packages` |
| Bugreport / ANR | `adb bugreport / pull /data/anr` |
| Retrieve / Cleanup logs | `adb logcat -d / -c` |
| Memory / CPU / Battery | `dumpsys meminfo/cpuinfo/battery` |
| Uptime | `uptime` |
| Top / GFX / Wakelocks / Net | `top` / `dumpsys gfxinfo/netstats` / `/proc/wakelocks` |

### Tab 3: System

| Feature | ADB Command |
|---------|-------------|
| Custom shell | `adb shell <any command>` |
| Port forward / reverse | `adb forward / reverse / --list / --remove-all` |
| Service toggles (svc) | `svc wifi/data/bluetooth/nfc enable/disable` |
| Android Settings | `adb shell settings list/get/put` (system/global/secure) |
| Content query | `adb shell content query --uri` |
| Process list / kill | `ps -A` / `kill <pid>` |
| Dumpsys services | 17 common services dropdown + custom input |
| Kernel / CPU info | `cat /proc/version` / `cat /proc/cpuinfo` |
| PM features | `adb shell pm list features` |
| Battery simulation | `dumpsys battery set level/status / reset` |
| Quick settings | Animation toggle / stay awake |
| IME management | `adb shell ime list / set` |
| Emulator SMS/Call/GPS | `adb emu sms send / call / geo fix` |

### Tab 4: Remote (scrcpy)

| Feature | Description |
|---------|-------------|
| Screen mirroring | scrcpy launch with preset configs (resolution, FPS, bitrate) |
| D-Pad | Directional pad: up/down/left/right/center |
| Quick keys | 16 system keys: HOME, BACK, POWER, RECENTS, MENU, VOL+/-, APP_SWITCH, NOTIFICATION, SETTINGS, CAMERA, SEARCH, MEDIA controls, ENTER |
| Touch gestures | Tap, swipe, long press, drag with coordinates |
| Capture | Screenshot and screen recording via scrcpy |

### Standalone Dialogs

| Dialog | Description |
|--------|-------------|
| **App Manager** | App list (user/system/vendor), batch uninstall/disable/enable, APK backup (ZIP)/restore, permission management, presets (JSON import/export) |
| **File Explorer** | Device file browser: navigation, Pull/Push, new folder/file, delete/rename, text viewer/editor, image preview, copy/cut/paste, chmod, APK install, shell script execution, sort/search |
| **Live Logcat** | Real-time log stream (`-v threadtime`), combined Level+Package+Tag filter, color highlighting (QSyntaxHighlighter), 8000 line buffer, export to txt, fetch current foreground app package |
| **Screenshot Viewer** | Zoom (Ctrl+Scroll), multi-image navigation, copy to clipboard, save as, open folder, pin/unpin toggle |

---

## Theme System

Light/Dark dual theme with one-click toggle via toolbar button, managed by `BaseStyles`:

- 28 color keys per theme (WINDOW_BG, PANEL_BG, INPUT_BG, BUTTON_BG, TEXT_PRIMARY, etc.)
- Font: `Segoe UI 12px` base, `Courier New 10px` monospace
- All components (panels, dialogs, popups) auto-respond via `BaseStyles.theme_changed` signal
- QSS templates: `BUTTON_STYLE()`, `INPUT_STYLE()`, `GROUP_BOX_STYLE()`, `TOOLBAR_STYLE()`, `PANEL_BASE_STYLE()`, etc.
- Theme persisted to settings, restored on startup
- Splitter handle color follows theme (BORDER_COLOR)
- QWidget base background rule ensures consistent dark mode coverage across all child widgets

---

## Settings System

Managed by `AppSettings` singleton (`resources/app_settings.json`):

| Setting | Default | Description |
|---------|---------|-------------|
| `theme` | Light | Current theme |
| `font_base_size` | 12 | Base font size |
| `window_width` / `window_height` | 1200 / 650 | Window dimensions (adjustable in Settings) |
| `left_panel_width` / `right_panel_width` | auto-calc | Panel widths (linked: left + right + overhead = window width) |
| `save_directory` | `~/ADBLab` | Default file save location |
| `log_max_lines` | 2000 | Log panel max line count |
| `monkey_default_count` | 10000 | Monkey test default event count |
| `screen_record_duration` | 180 | Default recording duration (seconds) |
| `confirm_dangerous_ops` | true | Confirm before dangerous operations |
| `auto_refresh_on_connect` | true | Auto-refresh device list after connect |

Settings dialog: real-time preview, window size and panel widths with linked constraints (left max = window - right min - overhead).

---

## Key Features

- **USB auto-detection**: 3-second `adb devices` poll, auto-refresh on device count change
- **Multi-device dialogs**: App Manager / File Explorer / Live Logcat open independent windows per selected device
- **Live Logcat combined filter**: Level + Package (pidof PID lookup) + Tag with color highlighting
- **Batch install APK**: Multi-file × multi-device queued installation
- **Theme persistence**: Theme saved on toggle, restored on next launch
- **QSplitter draggable divider**: Independent left/right panel resizing, sizes saved on drag

---

## Dependencies

### Python (requirements.txt)

| Package | Version | Purpose |
|---------|---------|---------|
| PySide6 / PySide6_Essentials / PySide6_Addons | 6.8.1.1 | Qt 6 GUI |
| loguru | 0.7.3 | Advanced logging (legacy) |
| PyYAML | 6.0.2 | YAML parsing |
| ruamel.yaml | latest | YAML read/write (preserves comments) |
| Requests | 2.32.5 | HTTP client |
| pyinstaller | latest | EXE packaging |
| Pillow | latest | Image processing |

### System Requirements

- **ADB** — bundled in `scrcpy-win64-v3.3.1/` (no system PATH needed)
- **aapt** — APK parsing (external tool)
- **Java JRE** — for `chkbugreport-0.5-215.jar`

---

## CI/CD

### Build-exe.yaml
- **Trigger**: `workflow_dispatch` manual or push to `main`
- **Environment**: `windows-latest`, Python 3.11 x64
- **Build**: PyInstaller `--onefile --windowed` single EXE
- **Artifact**: `ADBLab-x64-v2.0.{run_id}.exe` → GitHub Release

### Auto-Clean.yaml
- **Trigger**: 1st of each month 18:00 UTC or manual
- **Action**: Delete runs older than 2 days, keep latest 8 releases

---

## Development

### Quick Start
```bash
pip install -r requirements.txt
python main.py
```

### Code Conventions
- UI strictly separated from business logic
- All ADB operations must be async, never block the main thread
- Signal definitions centralized in `*_signals.py`
- New model methods follow `@async_command` decorator pattern
- New controller methods follow `handler_map` dispatch pattern
- All dialogs inherit from the ADBLab theme system (`BaseStyles`)
- YAML persistence via `DeviceStore` class
- Logging via `LogService` singleton
- User-facing strings in English only
