"""验证 ADB 客户端解析的候选顺序、缓存失效与消费方惰性取值。"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from core import exec as execution
from core.adb_bridge import ADBBridge
from utils import adb_resolver

_ENVIRONMENT_KEYS = ("ADB_PATH", "ANDROID_HOME", "ANDROID_SDK_ROOT", "LOCALAPPDATA")


@pytest.fixture(autouse=True)
def reset_resolver_cache() -> Iterator[None]:
    """每个用例前后都清空解析缓存与客户端选择，避免用例之间互相影响。"""

    adb_resolver.invalidate_adb_path_cache()
    adb_resolver.set_client_preference(adb_resolver.CLIENT_PREFERENCE_AUTO)
    yield
    adb_resolver.invalidate_adb_path_cache()
    adb_resolver.set_client_preference(adb_resolver.CLIENT_PREFERENCE_AUTO)


def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENVIRONMENT_KEYS:
        monkeypatch.delenv(name, raising=False)


def _same_path(actual: str | None, expected: str) -> bool:
    """按平台规范化比较路径，忽略分隔符与大小写差异。"""

    return actual is not None and os.path.normcase(os.path.abspath(actual)) == os.path.normcase(
        os.path.abspath(expected)
    )


def _existing_paths(monkeypatch: pytest.MonkeyPatch, paths: list[str]) -> None:
    """只让列出的候选通过存在性检查；用与解析器相同的路径规范化。"""

    known = {os.path.normcase(os.path.abspath(path)) for path in paths}
    monkeypatch.setattr(
        adb_resolver.os.path,
        "isfile",
        lambda path: os.path.normcase(os.path.abspath(path)) in known,
    )


def _which(monkeypatch: pytest.MonkeyPatch, path: str | None) -> None:
    monkeypatch.setattr(adb_resolver.shutil, "which", lambda _name: path)


def _events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        adb_resolver.adb_debug, "event",
        lambda name, **fields: captured.append((name, fields)),
    )
    return captured


def _prepare_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_environment(monkeypatch)
    monkeypatch.setattr(adb_resolver.sys, "platform", "win32")
    monkeypatch.setattr(
        adb_resolver, "bundled_tool_path", lambda bundle, name: "C:/bundle/adb.exe"
    )


def test_windows_prefers_bundled_over_environment_and_sdk(monkeypatch):
    _prepare_windows(monkeypatch)
    monkeypatch.setattr(adb_resolver, "resource_path", lambda relative: "C:/bundle/adb.exe")
    monkeypatch.setenv("ADB_PATH", "C:/env/adb.exe")
    monkeypatch.setenv("ANDROID_HOME", "C:/sdk")
    _which(monkeypatch, "C:/path/adb.exe")
    _existing_paths(monkeypatch, [
        "C:/bundle/adb.exe", "C:/env/adb.exe",
        "C:/sdk/platform-tools/adb.exe", "C:/path/adb.exe",
    ])
    events = _events(monkeypatch)

    assert _same_path(adb_resolver.resolve_adb_path(), "C:/bundle/adb.exe")
    selected = next(fields for name, fields in events if name == "resolve_result")
    assert selected["source"] == "bundled"


def test_windows_falls_back_to_environment_then_sdk_then_path(monkeypatch):
    _prepare_windows(monkeypatch)
    monkeypatch.setenv("ADB_PATH", "C:/env/adb.exe")
    monkeypatch.setenv("ANDROID_HOME", "C:/sdk")
    _which(monkeypatch, "C:/path/adb.exe")
    # 内置缺失、ADB_PATH 指向不存在的文件：应落到 SDK，而不是 PATH。
    _existing_paths(monkeypatch, ["C:/sdk/platform-tools/adb.exe", "C:/path/adb.exe"])
    events = _events(monkeypatch)

    assert _same_path(adb_resolver.resolve_adb_path(), "C:/sdk/platform-tools/adb.exe")
    assert next(f for n, f in events if n == "resolve_result")["source"] == "sdk_home"

    adb_resolver.invalidate_adb_path_cache()
    _existing_paths(monkeypatch, ["C:/env/adb.exe", "C:/path/adb.exe"])
    assert _same_path(adb_resolver.resolve_adb_path(), "C:/env/adb.exe")

    adb_resolver.invalidate_adb_path_cache()
    monkeypatch.delenv("ADB_PATH")
    _existing_paths(monkeypatch, ["C:/path/adb.exe"])
    assert _same_path(adb_resolver.resolve_adb_path(), "C:/path/adb.exe")


@pytest.mark.parametrize(
    "variable, root, expected",
    [
        ("ANDROID_HOME", "C:/home", "C:/home/platform-tools/adb.exe"),
        ("ANDROID_SDK_ROOT", "C:/root", "C:/root/platform-tools/adb.exe"),
        ("LOCALAPPDATA", "C:/local", "C:/local/Android/Sdk/platform-tools/adb.exe"),
    ],
)
def test_windows_accepts_each_sdk_location(monkeypatch, variable, root, expected):
    _prepare_windows(monkeypatch)
    monkeypatch.setenv(variable, root)
    _which(monkeypatch, None)
    _existing_paths(monkeypatch, [expected])

    assert _same_path(adb_resolver.resolve_adb_path(), expected)


def test_non_windows_never_uses_bundled_windows_binary(monkeypatch):
    _isolate_environment(monkeypatch)
    monkeypatch.setattr(adb_resolver.sys, "platform", "linux")
    monkeypatch.setattr(
        adb_resolver, "bundled_tool_path", lambda bundle, name: "/repo/scrcpy-win64/adb.exe"
    )
    _which(monkeypatch, "/usr/bin/adb")
    _existing_paths(monkeypatch, ["/repo/scrcpy-win64/adb.exe"])

    assert _same_path(adb_resolver.resolve_adb_path(), "/usr/bin/adb")


def test_invalidate_cache_rescans_after_client_installation(monkeypatch):
    _isolate_environment(monkeypatch)
    monkeypatch.setattr(adb_resolver.sys, "platform", "linux")
    _which(monkeypatch, None)
    assert adb_resolver.resolve_adb_path() is None

    _which(monkeypatch, "/usr/bin/adb")
    # 仍是旧缓存：这正是「重新检测」必须显式失效的原因。
    assert adb_resolver.resolve_adb_path() is None

    adb_resolver.invalidate_adb_path_cache()
    assert _same_path(adb_resolver.resolve_adb_path(), "/usr/bin/adb")


def test_list_adb_candidates_keeps_unavailable_entries(monkeypatch):
    """候选列表保留不可用项，界面才能解释"为什么没识别到"。"""

    _prepare_windows(monkeypatch)
    monkeypatch.setattr(adb_resolver, "resource_path", lambda relative: "C:/bundle/adb.exe")
    monkeypatch.setenv("ADB_PATH", "C:/env/adb.exe")
    monkeypatch.setenv("ANDROID_HOME", "C:/home")
    _which(monkeypatch, "C:/path/adb.exe")
    _existing_paths(monkeypatch, ["C:/bundle/adb.exe", "C:/path/adb.exe"])

    candidates = adb_resolver.list_adb_candidates()

    by_source = {candidate.source: candidate for candidate in candidates}
    assert set(by_source) == {"bundled", "env", "PATH"}
    assert "sdk_home" not in by_source
    assert by_source["bundled"].exists is True
    assert by_source["env"].exists is False
    assert by_source["PATH"].exists is True


def test_preference_pins_single_candidate_without_fallback(monkeypatch):
    """选择命名来源后只使用该来源；缺失时返回 None，不静默换用其它 adb。"""

    _prepare_windows(monkeypatch)
    _which(monkeypatch, "C:/path/adb.exe")
    _existing_paths(monkeypatch, ["C:/bundle/adb.exe", "C:/path/adb.exe"])

    adb_resolver.set_client_preference("PATH")
    assert _same_path(adb_resolver.resolve_adb_path(), "C:/path/adb.exe")

    adb_resolver.set_client_preference("env")  # ADB_PATH 未设置
    assert adb_resolver.resolve_adb_path() is None

    adb_resolver.set_client_preference("C:/custom/adb.exe")
    _existing_paths(monkeypatch, ["C:/custom/adb.exe"])
    assert _same_path(adb_resolver.resolve_adb_path(), "C:/custom/adb.exe")

    adb_resolver.set_client_preference("auto")
    _existing_paths(monkeypatch, ["C:/bundle/adb.exe"])
    assert _same_path(adb_resolver.resolve_adb_path(), "C:/bundle/adb.exe")


def test_exec_program_cache_follows_resolver_invalidation(monkeypatch):
    monkeypatch.setattr(execution, "_adb_path", None)
    monkeypatch.setattr("utils.adb_resolver.adb_path", lambda: "first-adb")
    assert execution.resolve_adb_program() == "first-adb"

    monkeypatch.setattr("utils.adb_resolver.adb_path", lambda: "second-adb")
    assert execution.resolve_adb_program() == "first-adb"

    execution.reset_adb_program_cache()
    assert execution.resolve_adb_program() == "second-adb"


def test_bridge_defers_missing_adb_and_follows_later_resolution(monkeypatch):
    monkeypatch.setattr("core.adb_bridge.adb_path", lambda: "adb")

    bridge = ADBBridge()
    assert bridge.path == "adb"

    monkeypatch.setattr("core.adb_bridge.adb_path", lambda: "C:/new/adb.exe")
    assert bridge.path == "C:/new/adb.exe"
    assert ADBBridge("explicit-adb").path == "explicit-adb"
