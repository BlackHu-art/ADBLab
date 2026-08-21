---
kind: function
---

# test_native_screen_resize_before_signal_does_not_replace_preferred_size(qt_application, signal_kind, signal_after_debounce)

- 定义于：[[tests.test_main_window_layout]]
- 全名：tests.test_main_window_layout.test_native_screen_resize_before_signal_does_not_replace_preferred_size

## 调用

- [[gui.main_frame.MainFrame._unbind_window_screen]]
- [[tests.test_main_window_layout._FakeScreenAdapter.emit_available_geometry_changed]]
- [[tests.test_main_window_layout._FakeScreenAdapter.emit_logical_dpi_changed]]
- [[tests.test_main_window_layout._FakeScreenAdapter.emit_screen_changed]]
- [[tests.test_main_window_layout._FakeScreenAdapter.token_count]]
- [[tests.test_main_window_layout.build_main_frame]]
- [[tests.ui_geometry_helpers.wait_until]]

## 实例化

- [[tests.test_main_window_layout._FakeScreen]]
- [[tests.test_main_window_layout._FakeScreenAdapter]]
- [[tests.test_main_window_layout._MainFrameSettings]]

