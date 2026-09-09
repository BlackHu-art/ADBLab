"""正式发布版本的解析、比较及下载链接信任边界。"""

import pytest


def release_payload(tag="v3.2.12", **changes):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/BlackHu-art/ADBLab/releases/tag/{tag}",
        "published_at": "2026-09-09T08:00:00Z",
        "draft": False,
        "prerelease": False,
        **changes,
    }


@pytest.mark.parametrize("tag,current,status", [
    ("v3.2.10", "3.2.9", "available"),
    ("3.3.0", "3.2.99", "available"),
    ("v4.0.0", "3.99.99", "available"),
    ("v3.2.11", "3.2.11", "current"),
    ("v3.2.10", "3.2.11", "ahead"),
])
def test_release_comparison_uses_numeric_version_parts(tag, current, status):
    from services.app_update import parse_release, release_status

    release = parse_release(release_payload(tag))
    assert release_status(release, current) == status
    assert release.version == tag.removeprefix("v")
    assert release.published_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("tag", [
    "v3.2", "v3.2.11-beta.1", "v03.2.11", "v３.2.11", "v3.2.11\n",
    "v3.2.11/../../other", "3.2.-1", "v3.2.100000000000000000000", "",
])
def test_unrecognised_release_tag_cannot_be_reported_as_current(tag):
    from services.app_update import parse_release

    with pytest.raises(ValueError):
        parse_release(release_payload(tag))


@pytest.mark.parametrize("changes", [
    {"draft": True}, {"prerelease": True}, {"draft": "false"},
    {"published_at": None}, {"published_at": "2026-09-09"},
    {"html_url": "http://github.com/BlackHu-art/ADBLab/releases/tag/v3.2.12"},
    {"html_url": "https://github.com.evil.test/BlackHu-art/ADBLab/releases/tag/v3.2.12"},
    {"html_url": "https://github.com/other/repo/releases/tag/v3.2.12"},
    {"html_url": "https://github.com/BlackHu-art/ADBLab/releases/tag/v3.2.11"},
    {"html_url": "file:///C:/Windows/System32/cmd.exe"},
])
def test_release_requires_stable_metadata_and_matching_trusted_url(changes):
    from services.app_update import parse_release

    with pytest.raises(ValueError):
        parse_release(release_payload(**changes))


@pytest.mark.parametrize("payload", [None, [], {}, {"tag_name": "v3.2.12"}])
def test_incomplete_response_is_rejected(payload):
    from services.app_update import parse_release

    with pytest.raises(ValueError):
        parse_release(payload)
