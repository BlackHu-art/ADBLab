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


def installer_payload(**changes):
    return {
        "id": 12,
        "name": "ADBLab-win-x64-v3.2.12-setup.exe",
        "state": "uploaded",
        "size": 3,
        "digest": "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "browser_download_url": (
            "https://github.com/BlackHu-art/ADBLab/releases/download/v3.2.12/"
            "ADBLab-win-x64-v3.2.12-setup.exe"
        ),
        **changes,
    }


def test_installer_is_bound_to_the_same_release_without_changing_browser_contract():
    from services.app_update import UpdateSnapshot, parse_installer_asset, parse_release

    payload = release_payload(id=5, assets=[installer_payload()])
    release = parse_release(payload)
    asset = parse_installer_asset(payload, release)
    assert (asset.release_id, asset.asset_id, asset.tag, asset.version) == (
        5, 12, "v3.2.12", "3.2.12",
    )
    assert asset.name == "ADBLab-win-x64-v3.2.12-setup.exe"
    assert asset.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert UpdateSnapshot(release=release).installer_asset is None
    assert UpdateSnapshot(release=release, installer_asset=asset).release is release


@pytest.mark.parametrize("changes", [
    {"id": True}, {"id": 0}, {"id": "12"}, {"state": "starter"},
    {"size": True}, {"size": 0}, {"size": -1}, {"size": 2 ** 31 + 1},
    {"size": "3"}, {"digest": None}, {"digest": ""}, {"digest": "sha256:" + "a" * 63},
    {"digest": "sha1:" + "a" * 64}, {"digest": "sha256:" + "g" * 64},
    {"name": "ADBLab-win-x64-v3.2.11-setup.exe"},
    {"name": "ADBLab-linux-x64-v3.2.12-setup.exe"},
    {"browser_download_url": "http://github.com/BlackHu-art/ADBLab/releases/download/v3.2.12/x"},
    {"browser_download_url": "https://github.com.evil.test/BlackHu-art/ADBLab/releases/download/x"},
    {"browser_download_url": "https://github.com/other/repo/releases/download/v3.2.12/x"},
    {"browser_download_url": installer_payload()["browser_download_url"] + "?download=1"},
    {"browser_download_url": installer_payload()["browser_download_url"] + "#fragment"},
])
def test_installer_rejects_untrusted_asset_fields_without_rejecting_release(changes):
    from services.app_update import parse_installer_asset, parse_release

    payload = release_payload(id=5, assets=[installer_payload(**changes)])
    release = parse_release(payload)
    with pytest.raises(ValueError):
        parse_installer_asset(payload, release)
    assert release.url.endswith("/tag/v3.2.12")


@pytest.mark.parametrize("changes", [
    {"id": None}, {"id": True}, {"id": -1}, {"assets": None}, {"assets": []},
    {"assets": [installer_payload(), installer_payload(id=13)]},
    {"draft": True}, {"prerelease": True},
    {"tag_name": "v3.2.13", "html_url": "https://github.com/BlackHu-art/ADBLab/releases/tag/v3.2.13"},
    {"published_at": "2026-09-10T08:00:00Z"},
])
def test_installer_rejects_missing_ambiguous_or_different_release(changes):
    from services.app_update import parse_installer_asset, parse_release

    payload = release_payload(id=5, assets=[installer_payload()])
    release = parse_release(payload)
    with pytest.raises(ValueError):
        parse_installer_asset({**payload, **changes}, release)
