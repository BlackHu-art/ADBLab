"""功能页的响应行、原生表单和结果区共用完整的页面宽度。"""

import pytest

from adblab.application.action_results import ActionItem, ActionResult, ActionSpec
from core.settings_manager import AppSettings
from gui.styles import BaseStyles
from gui.widgets.responsive_controller import ResponsiveCoordinator
from tests.test_responsive_panels import (
    _close_feature_panel,
    _resize_feature_viewport,
    _show_feature_panel,
)
from tests.ui_geometry_helpers import assert_non_overlapping, mapped_rect

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("page_name", ["apps", "system"])
@pytest.mark.parametrize("font_size", [12, 22])
@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_all_page_rows_align_with_sections_and_nonresponsive_controls(
    qt_application, monkeypatch, page_name, font_size, theme,
):
    settings = {"font_family": "Sans Serif", "ui_font_size": font_size, "log_font_size": 11}
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: settings))
    monkeypatch.setattr(ResponsiveCoordinator, "RESIZE_DEBOUNCE_MS", 1)
    BaseStyles.reload_from_settings()
    BaseStyles.switch_theme(theme)
    owner, page, scroll, content = _show_feature_panel(
        page_name, 700, font_size, qt_application, monkeypatch, patch_font_factory=False,
    )
    try:
        if page_name == "system":
            controls = page.intent_controls
            controls.advanced_toggle.click()
            controls.add_extra.click()
            extra = controls.extra_rows[0]
            extra.key.setText("example")
            extra.value.setText("value")
            full_width_controls = (
                controls.advanced_toggle, controls.advanced, controls.extras,
                controls.add_extra, extra.widget,
            )
            groups = page._system_section_groups
        else:
            result = ActionResult(
                "alignment", ActionSpec("alignment", "apps.diagnostics", "诊断", "text"),
                (), 1, "succeeded", items=(ActionItem(
                    "job", "", "设备 1", "succeeded", "合成诊断输出",
                    artifacts=("/synthetic-home/report.txt",),
                ),), finished_at=2,
            )
            page.report_artifacts.present(result)
            page.diagnostic_results.present(result)
            full_width_controls = (
                page.report_artifacts, page.report_artifacts.files,
                page.diagnostic_results, page.diagnostic_results.targets,
                page.diagnostic_results.search, page.diagnostic_results.output,
            )
            groups = page._apps_section_groups

        # 附加参数维持既有单行和横向溢出兜底；此处验证可完整容纳时的右界。
        narrow_width = 540 if font_size == 22 else 430
        for width in (narrow_width, 700, 1000, narrow_width):
            _resize_feature_viewport(qt_application, owner, page, scroll, width)
            assert content.width() == scroll.viewport().width() == width
            assert scroll.horizontalScrollBar().maximum() == 0
            expected_right = content.rect().right()
            for group in groups:
                if group.isVisibleTo(content):
                    assert mapped_rect(group, content).right() == expected_right
            visible_rows = 0
            for binding in page._responsive_rows:
                widgets = tuple(w for w in binding.widgets() if w.isVisibleTo(content))
                if not widgets:
                    continue
                visible_rows += 1
                row = widgets[0].parentWidget()
                assert mapped_rect(row, content).right() == expected_right
                # 只检查网格最右侧，不拉伸换行后未占满的尾行或自然宽度按钮。
                assert max(mapped_rect(w, content).right() for w in widgets) == expected_right
                assert_non_overlapping(widgets, content)
            assert visible_rows > 0
            for control in full_width_controls:
                assert control.isVisibleTo(content)
                assert mapped_rect(control, content).right() == expected_right
            if page_name == "system":
                assert mapped_rect(extra.remove, content).right() == expected_right
                assert extra.key.text() == "example" and extra.value.text() == "value"
    finally:
        # 独立滚动窗口须先关闭，再释放其逻辑宿主，保持与主窗口一致的退出顺序。
        scroll.close()
        owner.shutdown()
        _close_feature_panel(owner)
