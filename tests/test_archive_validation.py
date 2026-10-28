import zipfile
from types import SimpleNamespace

import pytest

from utils import archive


@pytest.mark.parametrize(
    "sizes,compressed,accepted",
    [
        ([512 * 1024 * 1024], 0, True),
        ([512 * 1024 * 1024, 1], 0, False),
        ([-1, 512 * 1024 * 1024], 0, True),
        ([1048575], 1, True),
        ([1048576], 0, True),
        ([1048576], 5242, True),
        ([1048576], 5216, False),
    ],
)
def test_validation_and_extraction_preserve_exact_size_and_ratio_rules(
    tmp_path, sizes, compressed, accepted
):
    extracted = []
    members = [
        SimpleNamespace(filename=f"{index}.apk", file_size=size, compress_size=compressed)
        for index, size in enumerate(sizes)
    ]
    zf = SimpleNamespace(infolist=lambda: members, extractall=extracted.append)
    target = tmp_path / "target"
    if accepted:
        archive.validate_zip_archive(zf, target)
        assert extracted == []
        archive.safe_extract_zip(zf, target)
        assert extracted == [target.resolve()]
    else:
        for operation in (archive.validate_zip_archive, archive.safe_extract_zip):
            with pytest.raises(ValueError):
                operation(zf, target)
        assert extracted == []
    assert not target.exists()


@pytest.mark.parametrize("count", [10000, 10001])
def test_validation_member_limit_is_inclusive(tmp_path, count):
    member = SimpleNamespace(filename="one.apk", file_size=0, compress_size=0)
    zf = SimpleNamespace(infolist=lambda: [member] * count)
    if count == 10000:
        archive.validate_zip_archive(zf, tmp_path)
    else:
        with pytest.raises(ValueError, match="too many members"):
            archive.validate_zip_archive(zf, tmp_path)


@pytest.mark.parametrize("name", ["../escape.apk", "nested/../../escape.apk"])
def test_unsafe_path_rejected_before_any_extraction(tmp_path, name):
    path = tmp_path / "input.zip"
    target = tmp_path / "output"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("good.apk", b"apk")
        zf.writestr(name, b"apk")
    with zipfile.ZipFile(path) as zf:
        for operation in (archive.validate_zip_archive, archive.safe_extract_zip):
            with pytest.raises(ValueError, match="Unsafe ZIP member path"):
                operation(zf, target)
    assert not target.exists()
    assert not (tmp_path / "escape.apk").exists()


def test_validation_does_not_write_and_extraction_preserves_content(tmp_path):
    path = tmp_path / "input.zip"
    target = tmp_path / "output"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("nested/base.apk", b"apk")
    with zipfile.ZipFile(path) as zf:
        archive.validate_zip_archive(zf, target)
        assert not target.exists()
        archive.safe_extract_zip(zf, target)
    assert (target / "nested/base.apk").read_bytes() == b"apk"
