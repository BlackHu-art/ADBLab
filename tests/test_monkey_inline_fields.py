"""验证 Monkey 参数采用标签在前的紧凑布局，分组标题不额外占用工具行。"""

import pytest
from PySide6.QtCore import Qt

from tests.test_dialog_languages import dialog_language as dialog_language
from tests.test_monkey_alignment import monkey_page as monkey_page
from tests.test_responsive_panels import _resize_feature_viewport
from tests.ui_geometry_helpers import assert_non_overlapping, mapped_rect

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("width,font_size,language,font_family", [
    (780, 12, "zh_CN", "Segoe UI"), (1200, 22, "zh_CN", "Segoe UI"),
    (1000, 12, "en_US", "Segoe UI"), (780, 12, "zh_CN", "Microsoft YaHei UI"),
])
def test_monkey_labels_precede_options_on_the_same_line(
    monkey_page, dialog_language, width, font_size, language, font_family,
):
    """正常宽度下说明与输入同行，所有参数标签保留原字段语义与等宽输入。"""
    dialog_language(language)
    _owner, apps, _scroll, content = monkey_page(width, font_size, font_family)
    for binding in (
        apps.monkey_parameter_binding, apps.monkey_seed_binding, apps.monkey_percentage_binding,
    ):
        widgets = binding.widgets()
        assert_non_overlapping(widgets, content)
        for label, field in zip(widgets[::2], widgets[1::2]):
            label_rect, field_rect = mapped_rect(label, content), mapped_rect(field, content)
            assert label_rect.right() < field_rect.left()
            assert abs(label_rect.center().y() - field_rect.center().y()) <= 2
            assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
            assert not label.wordWrap()
            assert label.alignment() == (
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            assert label.buddy() is field
            assert field.minimumWidth() >= 96
    if width == 780 and font_size == 12:
        assert apps.monkey_percentage_binding.applied_plan.mode.name == "three"
    for top_label, lower_label, top_field, lower_field in (
        (apps.monkey_events_label, apps.monkey_seed_mode_label,
         apps.monkey_events, apps.monkey_seed_mode),
        (apps.monkey_throttle_label, apps.monkey_seed_label,
         apps.monkey_throttle, apps.monkey_seed),
    ):
        assert mapped_rect(top_label, content).right() == mapped_rect(lower_label, content).right()
        assert mapped_rect(top_field, content).left() == mapped_rect(lower_field, content).left()


def test_monkey_group_captions_share_rows_with_options(monkey_page):
    """方案与异常开关各自与组标题同排，不在内容之间留下单独标题行。"""
    _owner, apps, _scroll, content = monkey_page(900, 12)
    for caption, option in (
        (apps.monkey_parameters_heading, apps.monkey_preset_bar),
        (apps.monkey_exceptions_heading, apps.monkey_chk_crashes),
    ):
        caption_rect, option_rect = mapped_rect(caption, content), mapped_rect(option, content)
        assert caption_rect.right() < option_rect.left()
        assert abs(caption_rect.center().y() - option_rect.center().y()) <= 2


def test_inline_fields_remain_readable_when_width_forces_vertical_fallback(
    qt_application, monkey_page,
):
    """极窄宽度仍保留完整编辑值和字段归属，不以压缩到零宽换取单行布局。"""
    owner, apps, scroll, content = monkey_page(900, 22)
    apps.monkey_events.setText("1000000")
    for width in (292, 160, 900):
        _resize_feature_viewport(qt_application, owner, apps, scroll, width)
        assert apps.monkey_events.text() == "1000000"
        for binding in (apps.monkey_parameter_binding, apps.monkey_percentage_binding):
            widgets = binding.widgets()
            assert_non_overlapping(widgets, content)
            for label, field in zip(widgets[::2], widgets[1::2]):
                assert field.width() >= field.minimumWidth()
                assert label.buddy() is field
