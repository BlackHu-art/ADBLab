"""包详情纯解析的既有协议与默认值。"""

import pytest

from services.apps.package_details import (
    has_package_detail,
    is_safe_package,
    parse_app_details,
    parse_batch_detail,
    parse_installed_apps,
    split_package_detail_sections,
)


@pytest.mark.parametrize(('value', 'accepted'), [
    (None, False), ('', False), ('a/b', False), ('a b', False),
    ('android', True), ('com.Example_APP', True), ('.', True),
])
def test_package_token_preserves_legacy_acceptance(value, accepted):
    assert is_safe_package(value) is accepted


def test_sections_require_matching_end_and_keep_legacy_marker_rules():
    output = (
        ' __ADBLAB_PKG_BEGIN_0__ \n旧值\n__ADBLAB_PKG_BEGIN_0__\n'
        '  名称=应用甲  \n__ADBLAB_PKG_END_1__\nversionCode=7\n'
        '__ADBLAB_PKG_END_0__\n__ADBLAB_PKG_BEGIN_1__\n截断'
    )
    assert split_package_detail_sections(output, 2) == {0: '  名称=应用甲  \nversionCode=7'}
    assert split_package_detail_sections(
        '__ADBLAB_PKG_BEGIN_0__\na\n__ADBLAB_PKG_BEGIN_1__\nb\n'
        '__ADBLAB_PKG_END_1__\n__ADBLAB_PKG_END_0__', 2,
    ) == {1: 'b'}
    assert has_package_detail('diagnostic versionCode=7')
    assert not has_package_detail('versionCode=?')


def test_batch_and_dialog_keep_distinct_label_and_version_defaults():
    output = 'versionCode=7\ncodePath=/data/app/demo  \nnonLocalizedLabel=X\n'
    assert parse_batch_detail('com.example.myAPP', output) == (
        'com.example.myAPP', 'myAPP', '', '',
    )
    assert parse_app_details('com.example.myAPP', output) == {
        'App Name': 'Myapp', 'Package': 'com.example.myAPP',
        'Path': '/data/app/demo  ', 'Version': '? (code 7)', 'Min SDK': '?', 'Target SDK': '?',
    }
    output = ('nonLocalizedLabel：不匹配\nnonLocalizedLabel=应用 名称\nversionName=1.2\n'
              'versionCode=7\nfirstInstallTime=2026-10-24 12:30\nminSdk=23\ntargetSdk=35')
    assert parse_batch_detail('com.demo', output) == (
        'com.demo', '应用 名称', '1.2 (7)', '2026-10-24',
    )
    assert parse_app_details('com.demo', output)['Version'] == '1.2 (code 7)'


def test_installed_rows_preserve_equals_paths_types_and_disabled_states():
    output = ('package:/data/app/a=b/base.apk=com.demo.my_APP\n'
              'package:/system/a/vendor/base=com.demo.system\n'
              'package:/vendor/base=com.demo.vendor\n'
              'package:/other/base=com.demo.other\n'
              'package:/data/app/base=com.demo.my_APP\n'
              'package:/empty=\ncom.raw\n')
    assert parse_installed_apps(output, 'package:com.demo.my_APP\n') == [
        ('My app', 'com.demo.my_APP', 'Disabled', 'User'),
        ('System', 'com.demo.system', 'Enabled', 'System'),
        ('Vendor', 'com.demo.vendor', 'Enabled', 'Vendor'),
        ('Other', 'com.demo.other', 'Enabled', 'Other'),
        ('My app', 'com.demo.my_APP', 'Disabled', 'User'),
        ('Raw', 'com.raw', 'Enabled', 'Other'),
    ]
