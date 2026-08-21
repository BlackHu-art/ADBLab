"""utils.atomic_text 的原子写入行为测试。"""

from __future__ import annotations

import pytest

from utils.atomic_text import atomic_write_text


def test_atomic_write_text_writes_content(tmp_path):
    target = tmp_path / "nested" / "out.txt"
    atomic_write_text(str(target), "hello\nworld")

    assert target.read_text(encoding="utf-8") == "hello\nworld"
    assert not list(target.parent.glob("*.tmp"))


def test_atomic_write_text_cleans_temp_on_replace_failure(tmp_path, monkeypatch):
    def failing_replace(src, dst):
        raise OSError("replace fail")

    monkeypatch.setattr("utils.atomic_text.os.replace", failing_replace)
    target = tmp_path / "out.txt"
    with pytest.raises(OSError):
        atomic_write_text(str(target), "data")
    assert not target.exists()
    assert not list(tmp_path.glob("*.tmp"))
