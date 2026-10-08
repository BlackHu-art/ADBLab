"""用合成凭据和无害图片验证日志、外部解码边界。"""

import gzip
import io
import sys
from base64 import b64decode

import pytest
from PySide6.QtGui import QImage, QImageReader

from core.diagnostics import DiagnosticJournal, redact_diagnostic
from core.exec import _command_summary
from tests.test_logging_contract import create_log_service  # noqa: F401


@pytest.mark.parametrize("args,expected", [
    (["shell", "curl -H 'Authorization: Bearer SYNTHETIC_SECRET' localhost"], "adb shell other"),
    (["shell", "SYNTHETIC_SECRET"], "adb shell other"),
    (["shell", "input", "SYNTHETIC_SECRET"], "adb shell input"),
    (["SYNTHETIC_SECRET"], "adb other"),
    (["-H", "SYNTHETIC_SECRET", "-P", "5037", "devices"], "adb devices"),
    (["-s", "SYNTHETIC_SECRET", "shell", "input", "text", "SYNTHETIC_SECRET"],
     "adb shell input text"),
])
def test_command_summary_never_includes_dynamic_tokens(args, expected):
    assert _command_summary(["adb", *args]) == expected


@pytest.mark.parametrize("value", [
    "Authorization: Bearer SYNTHETIC_SECRET",
    "authorization = Basic SYNTHETIC_SECRET",
    'Authorization: "Bearer SYNTHETIC_SECRET"',
    'Authorization: Digest username="SYNTHETIC_SECRET", realm="example"',
    'token="two words SYNTHETIC_SECRET"',
    "password='two words SYNTHETIC_SECRET'",
    "secret=SYNTHETIC_SECRET",
    'token="escaped \\" quote SYNTHETIC_SECRET"',
    'password="first line\nSYNTHETIC_SECRET"',
])
def test_named_credentials_are_fully_redacted(value):
    text = "before " + value + "; after"
    redacted = redact_diagnostic(text)
    assert "SYNTHETIC_SECRET" not in redacted
    assert "<redacted>" in redacted
    assert redacted.startswith("before ")
    if value.lower().startswith("authorization"):
        # 认证头可包含分号、逗号和引号，整行余部不当作独立诊断字段保留。
        assert redacted.endswith("<redacted>")
    else:
        assert redacted.endswith("; after")
    journal = DiagnosticJournal()
    assert journal.accept([("12:00", "ERROR", text)])
    assert "SYNTHETIC_SECRET" not in journal.text()


@pytest.mark.parametrize("value", [
    'Authorization: Digest username="example; SYNTHETIC_SECRET", realm="example"',
    'Authorization: "Bearer example" SYNTHETIC_SECRET',
])
def test_authorization_digest_delimiters_cannot_expose_quoted_credentials(value):
    assert "SYNTHETIC_SECRET" not in redact_diagnostic(value)


@pytest.mark.ui
def test_slow_shell_log_does_not_expose_credentials(request, monkeypatch):
    from core import exec as execution
    from utils import console_colors

    service = request.getfixturevalue("create_log_service")()
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(console_colors, "should_emit", lambda *_: True)
    monkeypatch.setattr(execution, "_slow_threshold_ms", lambda: 0)
    execution._log_if_slow(
        ["adb", "shell", "curl -H 'Authorization: Bearer SYNTHETIC_SECRET' localhost"],
        0, execution.CommandResult(success=True, output="ok", returncode=0), 5,
    )
    assert "[CMD] adb shell other" in stream.getvalue()
    assert "SYNTHETIC_SECRET" not in stream.getvalue()
    assert "out=2B" in stream.getvalue()
    assert not service.diagnostics.entries


_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="6">'
        b'<rect width="8" height="6"/></svg>')


@pytest.mark.ui
@pytest.mark.parametrize("content", [_SVG, gzip.compress(_SVG), b"invalid image"])
def test_all_external_image_boundaries_reject_non_raster(qt_application, tmp_path, content):
    from gui.dialogs.file_explorer_preview_tasks import PreviewReadWorker
    from gui.dialogs.file_explorer_view import _load_image_preview
    from gui.dialogs.screenshot_viewer_tasks import ScreenshotReadWorker, ScreenshotValidateWorker

    path = tmp_path / "renamed.png"
    path.write_bytes(content)
    worker = PreviewReadWorker(str(path))
    worker.run()
    assert worker.image.isNull() and worker.error == "invalid"
    assert _load_image_preview(str(path)).isNull()
    validator = ScreenshotValidateWorker((str(path),), QImageReader)
    validator.run()
    assert validator.rejected == [str(path)] and not validator.accepted
    reader = ScreenshotReadWorker(1, (str(path),), {}, QImageReader)
    results = []
    reader.image_ready.connect(lambda _generation, result: results.append(result))
    reader.run()
    assert len(results) == 1 and results[0][2].isNull() and results[0][3] == "invalid"


@pytest.mark.ui
@pytest.mark.parametrize("format_name", ["png", "jpeg", "bmp", "webp", "tiff"])
def test_raster_without_matching_extension_remains_supported(qt_application, tmp_path, format_name):
    from gui.dialogs.file_explorer_preview_tasks import PreviewReadWorker
    from gui.dialogs.screenshot_viewer_tasks import ScreenshotValidateWorker

    path = tmp_path / "no-extension"
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(0xFFABCDEF)
    assert image.save(str(path), format_name)
    validator = ScreenshotValidateWorker((str(path),), QImageReader)
    validator.run()
    assert validator.accepted == [str(path)]
    worker = PreviewReadWorker(str(path))
    worker.run()
    assert not worker.error and worker.image.size() == image.size()


@pytest.mark.ui
def test_imported_image_replaced_by_svg_is_not_decoded(qt_application, tmp_path):
    from gui.dialogs.screenshot_viewer_tasks import ScreenshotReadWorker, ScreenshotValidateWorker

    path = tmp_path / "replaced.png"
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    assert image.save(str(path))
    validator = ScreenshotValidateWorker((str(path),), QImageReader)
    validator.run()
    assert validator.accepted == [str(path)]
    path.write_bytes(_SVG)
    worker = ScreenshotReadWorker(1, (str(path),), {}, QImageReader)
    results = []
    worker.image_ready.connect(lambda _generation, result: results.append(result))
    worker.run()
    assert results[0][3] == "invalid" and results[0][2].isNull()


@pytest.mark.ui
def test_gif_remains_supported(qt_application, tmp_path):
    from gui.dialogs.file_explorer_preview_tasks import PreviewReadWorker

    path = tmp_path / "tiny.gif"
    path.write_bytes(b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"))
    worker = PreviewReadWorker(str(path))
    worker.run()
    assert not worker.error and worker.image.width() == 1


@pytest.mark.ui
def test_file_replaced_after_signature_cannot_change_decoder(qt_application, tmp_path):
    from gui.dialogs.screenshot_viewer_tasks import ScreenshotReadWorker

    path = tmp_path / "swapped.png"
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    assert image.save(str(path))

    def replace_then_create(target):
        path.write_bytes(_SVG)
        return QImageReader(target)

    worker = ScreenshotReadWorker(1, (str(path),), {}, replace_then_create)
    results = []
    worker.image_ready.connect(lambda _generation, result: results.append(result))
    worker.run()
    assert results[0][2].isNull() and results[0][3] in {"changed", "invalid"}
