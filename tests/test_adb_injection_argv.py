"""shell 注入防御契约测试：动态值经 shlex.quote/_shq 包裹，路径校验拒绝元字符。

覆盖三条防线：
1. mobileperf 的 _shq 单引号包裹与内嵌引号转义；
2. mobileperf 的 _is_safe_shell_path / _is_safe_basename 路径校验；
3. models 层设备端 shell 动词的动态值经 shlex.quote 包裹。
"""

import shlex
from unittest.mock import Mock

import pytest

from mobileperf.android.tools.androiddevice import (
    _is_safe_basename,
    _is_safe_shell_path,
    _shq,
)


class TestShqQuoting:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("com.example.app", "'com.example.app'"),
            ("a b", "'a b'"),
            ("a;rm -rf /", "'a;rm -rf /'"),
            ("$(id)", "'$(id)'"),
            ("a|b&c", "'a|b&c'"),
            ("a<b>c", "'a<b>c'"),
        ],
    )
    def test_wraps_value_in_single_quotes(self, raw, expected):
        assert _shq(raw) == expected

    def test_escapes_embedded_single_quotes_like_shlex_quote(self):
        assert _shq("a'b") == shlex.quote("a'b")

    @pytest.mark.parametrize(
        "dangerous",
        ["foo; rm -rf /data", "$(id)", "a|b", "x" + chr(96) + "id" + chr(96)],
    )
    def test_neutralizes_metacharacters_as_single_token(self, dangerous):
        assert shlex.split(_shq(dangerous)) == [dangerous]


class TestShellPathValidation:
    @pytest.mark.parametrize("bad", ["/data;rm", "a b", "a$(id)", "a|b", "a>b"])
    def test_rejects_shell_metacharacters(self, bad):
        assert _is_safe_shell_path(bad) is False

    def test_rejects_backtick(self):
        assert _is_safe_shell_path("a" + chr(96) + "id" + chr(96)) is False

    @pytest.mark.parametrize("good", ["/data/local/tmp", "file.txt", "a_b-1.c"])
    def test_accepts_plain_paths(self, good):
        assert _is_safe_shell_path(good) is True


class TestBasenameValidation:
    @pytest.mark.parametrize("bad", ["../etc", "a/b", ".", "..", "a;b"])
    def test_rejects_dangerous_basenames(self, bad):
        assert _is_safe_basename(bad) is False

    def test_rejects_backslash_separator(self):
        assert _is_safe_basename("a" + chr(92) + "b") is False

    @pytest.mark.parametrize("good", ["anr", "logcat.txt", "trace-2026_06_13"])
    def test_accepts_plain_basenames(self, good):
        assert _is_safe_basename(good) is True


class _Probe:
    def __init__(self):
        self._run = Mock(return_value={"success": True})


class TestModelShellCommandQuoting:
    def test_reset_permissions_quotes_package(self):
        from models.adb_system import ADBSystemMixin

        probe = _Probe()
        ADBSystemMixin.reset_permissions_async.__wrapped__(
            probe, "device-1", "com.example;rm"
        )

        cmd = probe._run.call_args.args[0]
        assert cmd == [
            "adb", "-s", "device-1", "shell", "pm", "reset-permissions",
            shlex.quote("com.example;rm"),
        ]
        assert cmd[-1] == "'com.example;rm'"

    def test_settings_put_quotes_namespace_key_and_value(self):
        from models.adb_advanced import ADBAdvanced

        probe = _Probe()
        ADBAdvanced.settings_put_async.__wrapped__(
            probe, "device-1", "secure", "key", "value;reboot"
        )

        cmd = probe._run.call_args.args[0]
        assert cmd == [
            "adb", "-s", "device-1", "shell", "settings", "put",
            shlex.quote("secure"), shlex.quote("key"), shlex.quote("value;reboot"),
        ]

    def test_input_text_quotes_free_text(self):
        from models.adb_app import ADBApp

        probe = _Probe()
        ADBApp.input_text_async.__wrapped__(probe, "device-1", "hello; rm -rf /")

        cmd = probe._run.call_args.args[0]
        assert cmd == [
            "adb", "-s", "device-1", "shell", "input", "text",
            shlex.quote("hello; rm -rf /"),
        ]
