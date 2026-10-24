"""安装器 Qt 下载的真实线程、受控传输与缓存生命周期回归。"""

import hashlib
import sys
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event

import pytest
from PySide6.QtCore import QThread, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from shiboken6 import isValid

from tests.test_qt_app_update import Reply
from tests.ui_geometry_helpers import wait_until

pytestmark = [pytest.mark.ui, pytest.mark.skipif(
    sys.platform != "win32", reason="仅 Windows 支持安装包原生缓存发布；其他平台拒绝下载",
)]


class DownloadReply(Reply):
    def __init__(self, request, parent, response, trace):
        super().__init__(request, parent)
        self.response = response
        self.trace = trace
        self.offset = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.deliver)
        self.timer.start(response.get("interval", 1))

    def readData(self, size):
        self.trace["reads"].append((size, QThread.currentThread()))
        return super().readData(size)

    def deliver(self):
        response = self.response
        self.setAttribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute, response.get("status", 200),
        )
        for name, value in response.get("headers", []):
            self.setRawHeader(name, value)
        if "redirect" in response:
            self.setAttribute(
                QNetworkRequest.Attribute.RedirectionTargetAttribute, QUrl(response["redirect"]),
            )
            self.setRawHeader(b"Location", response["redirect"].encode("ascii"))
        self.metaDataChanged.emit()
        if response.get("hold"):
            self.timer.stop()
            return
        body = response.get("body", b"")
        end = self.offset + response.get("chunk", len(body) or 1)
        self.feed(body[self.offset:end])
        self.offset = end
        if end >= len(body):
            self.timer.stop()
            if response.get("error") is not None:
                self.setError(response["error"], "controlled failure")
            self.setFinished(True)
            self.finished.emit()

    def abort(self):
        self.timer.stop()
        self.trace["aborted"] += 1
        if self.response.get("abort_ssl"):
            self.sslErrors.emit([])
        super().abort()


class DownloadManager(QNetworkAccessManager):
    def __init__(self, parent, responses, trace):
        super().__init__(parent)
        self.responses = responses
        self.trace = trace
        self.destroyed.connect(lambda: trace.update(manager_destroyed=True))

    def createRequest(self, operation, request, outgoingData=None):
        self.trace["requests"].append(QNetworkRequest(request))
        self.trace["threads"].append(QThread.currentThread())
        response = self.responses[len(self.trace["requests"]) - 1]
        return DownloadReply(request, self, response, self.trace)


def asset_for(data=b"installer fixture", **changes):
    from services.app_update import InstallerAsset

    return InstallerAsset(**{
        "release_id": 20, "asset_id": 30, "tag": "v999.0.0", "version": "999.0.0",
        "name": "ADBLab-win-x64-v999.0.0-setup.exe",
        "download_url": (
            "https://github.com/BlackHu-art/ADBLab/releases/download/v999.0.0/"
            "ADBLab-win-x64-v999.0.0-setup.exe"
        ),
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), **changes,
    })


def release_for(asset):
    from services.app_update import ReleaseInfo, UpdateSnapshot

    return UpdateSnapshot(
        status="available", installer_asset=asset, checked_at=datetime.now(timezone.utc),
        release=ReleaseInfo(
            asset.version, f"https://github.com/BlackHu-art/ADBLab/releases/tag/{asset.tag}",
            datetime(2026, 10, 24, tzinfo=timezone.utc),
        ),
    )


@pytest.fixture
def downloader(qt_application, tmp_path):
    from gui.adapters.installer_update import QtInstallerUpdate

    owners = []

    def create(responses, *, data=b"installer fixture", allowed=True, cache_root=None):
        trace = {"requests": [], "threads": [], "reads": [], "aborted": 0, "updates": []}
        owner = QtInstallerUpdate(
            cache_root=cache_root or tmp_path,
            manager_factory=lambda parent: DownloadManager(parent, responses, trace),
        )
        owners.append(owner)
        asset = asset_for(data)
        owner.changed.connect(trace["updates"].append)
        if allowed:
            owner.set_release(release_for(asset))
        return owner, asset, trace

    yield create
    for owner in owners:
        owner.prepare_shutdown()
        assert owner.wait(3), "download thread did not join"
        assert not owner.is_running()
        owner.deleteLater()
    wait_until(qt_application, lambda: all(not isValid(owner) for owner in owners))


def test_download_requires_explicit_fresh_release(qt_application, tmp_path):
    from gui.adapters.installer_update import QtInstallerUpdate

    owner = QtInstallerUpdate(cache_root=tmp_path)
    try:
        assert not owner.start(asset_for())
        assert not owner.is_running()
        assert owner.snapshot.status == "idle"
    finally:
        owner.prepare_shutdown()
        assert owner.wait(3)
        owner.deleteLater()
        wait_until(qt_application, lambda: not isValid(owner))


def test_download_streams_off_gui_thread_and_publishes_verified_file(downloader, qt_application):
    data = b"MZ" + b"bounded fixture" * 80000
    owner, asset, trace = downloader([{"body": data}], data=data)
    assert trace["requests"] == []
    assert owner.start(asset)
    assert not owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "ready")
    assert owner.wait(0)
    assert not owner.is_running()
    assert owner.snapshot.received == owner.snapshot.total == len(data)
    assert owner.snapshot.verified.path.read_bytes() == data
    assert owner.snapshot.verified.asset == asset
    assert trace["threads"] and all(t is not qt_application.thread() for t in trace["threads"])
    assert trace["reads"] and all(size <= 65536 for size, _thread in trace["reads"])
    assert trace["manager_destroyed"]
    request = trace["requests"][0]
    assert request.url().toString() == asset.download_url
    assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute) == (
        QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
    )
    assert not request.hasRawHeader("Authorization")


def test_shutdown_from_start_notification_sees_live_thread(downloader):
    owner, asset, _trace = downloader([{"hold": True}])
    running = []

    def close_on_start(snapshot):
        if snapshot.status == "downloading":
            running.append(owner.is_running())
            owner.prepare_shutdown()

    owner.changed.connect(close_on_start)
    assert owner.start(asset)
    assert owner.wait(3)
    assert running == [True]


@pytest.mark.parametrize("url", [
    "http://release-assets.githubusercontent.com/a",
    "https://example.invalid/a",
    "https://release-assets.githubusercontent.com.evil.invalid/a",
    "https://user@release-assets.githubusercontent.com/a",
    "https://release-assets.githubusercontent.com:444/a",
    "https://release-assets.githubusercontent.com/a#fragment",
    "/relative/location",
])
def test_redirect_outside_allowlist_cannot_download(downloader, qt_application, url):
    owner, asset, trace = downloader([{"status": 302, "redirect": url}])
    assert owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "error")
    assert owner.snapshot.error == "redirect"
    assert len(trace["requests"]) == 1
    assert owner.snapshot.verified is None


@pytest.mark.parametrize("redirects,expected", [(3, "ready"), (4, "error")])
def test_redirects_are_manually_limited_to_three(downloader, qt_application, redirects, expected):
    responses = [
        {"status": 302, "redirect": f"https://release-assets.githubusercontent.com/{index}?sig=ok"}
        for index in range(redirects)
    ] + [{"body": b"installer fixture"}]
    owner, asset, trace = downloader(responses)
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status in {"ready", "error"})
    assert owner.snapshot.status == expected
    assert len(trace["requests"]) == 4
    if expected == "error":
        assert owner.snapshot.error == "redirect"


def test_detached_redirect_reply_cannot_fail_next_request(downloader, qt_application):
    owner, asset, trace = downloader([
        {"status": 302, "redirect": "https://release-assets.githubusercontent.com/a",
         "hold": True, "abort_ssl": True},
        {"body": b"installer fixture"},
    ])
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status in {"ready", "error"})
    assert owner.snapshot.status == "ready"
    assert len(trace["requests"]) == 2


@pytest.mark.parametrize("response,error", [
    ({"status": None, "error": QNetworkReply.NetworkError.HostNotFoundError}, "network"),
    ({"status": None, "error": QNetworkReply.NetworkError.SslHandshakeFailedError}, "tls"),
    ({"status": 404}, "unavailable"),
    ({"status": 206, "body": b"installer fixture"}, "unavailable"),
    ({"body": b"installer fixture", "headers": [(b"Content-Length", b"18")]}, "invalid_response"),
    ({"body": b"installer fixture", "headers": [(b"Content-Length", b"bad")]}, "invalid_response"),
    ({"body": b"short"}, "verification"),
    ({"body": b"installer fixture plus"}, "verification"),
    ({"body": b"modified fixture!"}, "verification"),
])
def test_transport_and_integrity_failure_never_publish_ready(
    downloader, qt_application, tmp_path, response, error,
):
    owner, asset, trace = downloader([response])
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "error")
    assert owner.snapshot.error == error
    assert owner.snapshot.verified is None
    assert not any(snapshot.status == "ready" for snapshot in trace["updates"])
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("kind", ["idle", "total"])
def test_timeouts_abort_and_join_download_thread(downloader, qt_application, monkeypatch, kind):
    from gui.adapters.installer_update import QtInstallerUpdate

    monkeypatch.setattr(QtInstallerUpdate, "IDLE_TIMEOUT_MS", 15 if kind == "idle" else 1000)
    monkeypatch.setattr(QtInstallerUpdate, "TOTAL_TIMEOUT_MS", 1000 if kind == "idle" else 15)
    response = {"hold": True} if kind == "idle" else {
        "body": b"installer fixture", "chunk": 1, "interval": 5,
    }
    owner, asset, trace = downloader([response])
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "error")
    assert owner.snapshot.error == "timeout"
    assert owner.wait(0)
    assert trace["aborted"] == 1


def test_disk_failure_cleans_partial_file(downloader, qt_application, tmp_path, monkeypatch):
    from services.installer_update import DownloadWriter

    def no_space(_writer, _data):
        raise OSError("controlled disk full")

    monkeypatch.setattr(DownloadWriter, "write", no_space)
    owner, asset, _trace = downloader([{"body": b"installer fixture"}])
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "error")
    assert owner.snapshot.error == "disk"
    assert not list(tmp_path.rglob("*.part"))


def test_cancel_during_stream_rejects_late_ready_and_allows_retry(
    downloader, qt_application, tmp_path,
):
    data = b"x" * (4 * 1024 * 1024)
    owner, asset, trace = downloader([{"body": data}, {"body": data}], data=data)
    def cancel_after_progress(snapshot):
        if snapshot.status == "downloading" and snapshot.received > 0:
            owner.cancel()

    owner.changed.connect(cancel_after_progress)
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "cancelled")
    assert owner.wait(3)
    qt_application.processEvents()
    assert owner.snapshot.status == "cancelled"
    assert owner.snapshot.verified is None
    assert not list(tmp_path.rglob("*.part"))
    assert not any(item.status == "ready" for item in trace["updates"])
    owner.changed.disconnect(cancel_after_progress)
    assert owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "ready")
    assert owner.snapshot.verified.path.read_bytes() == data


@pytest.mark.parametrize("status", ["checking", "error", "current", "ahead"])
def test_new_release_state_revokes_ready_and_start_permission(downloader, qt_application, status):
    owner, asset, _trace = downloader([{"body": b"installer fixture"}])
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "ready")
    verified = owner.snapshot.verified
    owner.set_release(replace(release_for(asset), status=status))
    assert owner.snapshot.status == "idle"
    assert owner.snapshot.verified is None
    assert not owner.start(asset)
    assert verified.path.is_file()


def test_invalidated_inflight_result_cannot_restore_ready(downloader, qt_application):
    owner, asset, trace = downloader([{"hold": True}])
    owner.start(asset)
    wait_until(qt_application, lambda: bool(trace["requests"]))
    owner.set_release(replace(release_for(asset), status="checking"))
    assert owner.wait(3)
    qt_application.processEvents()
    assert owner.snapshot.status == "idle"
    assert not owner.start(asset)


def test_shutdown_waits_for_worker_io_without_blocking_gui(
    downloader, qt_application, monkeypatch,
):
    from services.installer_update import DownloadWriter

    entered, released = Event(), Event()
    original = DownloadWriter.write

    def delayed_write(writer, data):
        entered.set()
        assert released.wait(3), "test did not release disk boundary"
        return original(writer, data)

    monkeypatch.setattr(DownloadWriter, "write", delayed_write)
    owner, asset, trace = downloader([{"body": b"installer fixture"}])
    owner.start(asset)
    try:
        wait_until(qt_application, entered.is_set)
        owner.prepare_shutdown()
        before = len(trace["updates"])
        assert owner.is_running()
        assert not owner.wait(0.01)
        QTimer.singleShot(0, released.set)
        wait_until(qt_application, released.is_set)
        assert owner.wait(3)
        qt_application.processEvents()
        assert len(trace["updates"]) == before
        assert not owner.start(asset)
        assert not owner.is_running()
    finally:
        released.set()


def test_cached_installer_requires_fresh_release_and_is_revalidated(
    downloader, qt_application, tmp_path,
):
    first, asset, _trace = downloader([{"body": b"installer fixture"}])
    first.start(asset)
    wait_until(qt_application, lambda: first.snapshot.status == "ready")
    owner, _asset, trace = downloader([], allowed=False)
    assert not owner.start(asset)
    owner.set_release(release_for(asset))
    owner.start(asset)
    wait_until(qt_application, lambda: owner.snapshot.status == "ready")
    assert trace["requests"] == []
    assert owner.snapshot.verified.path == first.snapshot.verified.path
    owner.snapshot.verified.path.write_bytes(b"corrupted")
    third, _asset, trace = downloader([{"body": b"installer fixture"}])
    third.start(asset)
    wait_until(qt_application, lambda: third.snapshot.status == "ready")
    assert len(trace["requests"]) == 1
    assert third.snapshot.verified.path.read_bytes() == b"installer fixture"
