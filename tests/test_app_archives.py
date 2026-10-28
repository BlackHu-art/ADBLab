import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.apps import archives

PACKAGE = "org.example.app"


@pytest.mark.parametrize("paths", [("/app/one.apk",), ("/app/base.apk", "/app/split.apk")])
def test_backup_restore_round_trip(tmp_path, paths):
    events, pulls, installs = [], [], []
    archives.backup_app(PACKAGE, str(tmp_path), 0, **backup_options(events, puller(pulls, paths)))
    assert events[-1] == ("done", "backup")

    def execute(*args, **kwargs):
        installs.append(args)
        for path in args[4:]:
            assert Path(path).read_bytes() == f"/app/{Path(path).name}".encode()
        return response()

    archives.restore_apps(
        [str(tmp_path / f"backup_{PACKAGE}.zip")], **restore_options(events, execute)
    )
    assert [args[0] for args in installs] == [
        "install-multiple" if len(paths) > 1 else "install"
    ]
    assert events[-1] == ("done", "restore")


@pytest.mark.parametrize("reason", ["size", "members", "ratio", "path"])
def test_backup_rejects_restore_unsafe_archive_before_publish(tmp_path, monkeypatch, reason):
    from utils import archive as safety

    events, calls = [], []
    old = tmp_path / f"backup_{PACKAGE}.zip"
    old.write_bytes(b"old backup")
    compress = archives.shutil.make_archive
    if reason == "size":
        monkeypatch.setattr(safety, "MAX_ARCHIVE_BYTES", 1)
    elif reason == "members":
        monkeypatch.setattr(safety, "MAX_ARCHIVE_MEMBERS", 1)

    def staged(*args):
        output = compress(*args)
        if reason in {"ratio", "path"}:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("../escape.apk" if reason == "path" else "one.apk", b"a" * 1048576)
        return output

    monkeypatch.setattr(archives.shutil, "make_archive", staged)
    archives.backup_app(PACKAGE, str(tmp_path), 0, **backup_options(events, puller(calls)))
    assert old.read_bytes() == b"old backup"
    assert events[-1][0] == "failure"
    assert not any(event[0] == "done" for event in events)
    assert list(tmp_path.iterdir()) == [old]
    assert not any(args[0].startswith("install") for args, _ in calls)


@pytest.mark.parametrize("reason", ["size", "members", "ratio", "path"])
def test_restore_unsafe_archive_never_installs(tmp_path, monkeypatch, reason):
    from utils import archive as safety

    events, installs = [], []
    if reason == "size":
        monkeypatch.setattr(safety, "MAX_ARCHIVE_BYTES", 1)
    elif reason == "members":
        monkeypatch.setattr(safety, "MAX_ARCHIVE_MEMBERS", 1)
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("good.apk", b"apk")
        zf.writestr(
            "../escape.apk" if reason == "path" else "other.apk",
            b"a" * 1048576 if reason == "ratio" else b"apk",
        )

    def execute(*args, **kwargs):
        installs.append(args)
        return response()

    archives.restore_apps([str(path)], **restore_options(events, execute))
    assert installs == []
    assert events[0][0] == "failure"
    assert events[-1] == ("error", "Restore incomplete: 0 succeeded, 1 failed")
    assert list(tmp_path.iterdir()) == [path]


def test_backup_cancellation_after_validation_preserves_old_archive(tmp_path, monkeypatch):
    events, calls = [], []
    stopped = False
    old = tmp_path / f"backup_{PACKAGE}.zip"
    old.write_bytes(b"old backup")
    from utils.archive import validate_zip_archive

    def validate(zf, target):
        nonlocal stopped
        validate_zip_archive(zf, target)
        stopped = True

    monkeypatch.setattr(archives, "validate_zip_archive", validate)
    archives.backup_app(
        PACKAGE, str(tmp_path), 0, **backup_options(events, puller(calls), lambda: stopped)
    )
    assert old.read_bytes() == b"old backup"
    assert list(tmp_path.iterdir()) == [old]
    assert events[-1] == ("info", f"Backup aborted: {PACKAGE}")
    assert not any(event[0] in {"failure", "done"} for event in events)


def response(success=True, output="", error=""):
    return SimpleNamespace(success=success, output=output, stdout=output, error=error)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    original = archives.tempfile.TemporaryDirectory

    def temporary(*args, **kwargs):
        kwargs.setdefault("dir", str(tmp_path))
        return original(*args, **kwargs)

    monkeypatch.setattr(archives.tempfile, "TemporaryDirectory", temporary)


def notifications(events):
    return dict(
        log=lambda text: events.append(("log", text)),
        failure=lambda text: events.append(("failure", text)),
        feedback=lambda *args: events.append(args),
        completed=lambda text: events.append(("done", text)),
    )


def backup_options(events, execute, cancelled=lambda: False):
    return dict(
        execute=execute,
        cancelled=cancelled,
        progress=lambda *args: events.append(("progress", *args)),
        **notifications(events),
    )


def puller(calls, paths=("/app/base.apk", "/app/split.apk"), on_pull=None):
    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "shell":
            return response(output="\n".join(f"package:{path}" for path in paths))
        target = Path(args[2]) / Path(args[1]).name
        target.write_bytes(args[1].encode())
        return on_pull(args, calls) if on_pull else response()

    return execute


def archive(tmp_path, members=("one.apk", "two.apk"), name="backup_app.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for member in members:
            zf.writestr(member, b"fake apk")
    return str(path)


def restore_options(events, execute=None, cancelled=lambda: False, confirm_user=lambda: 0):
    return dict(
        execute=execute or (lambda *args, **kwargs: response()),
        cancelled=cancelled,
        confirm_user=confirm_user,
        **notifications(events),
    )


def test_backup_success_publishes_once_after_all_serial_pulls(tmp_path, monkeypatch):
    events, calls, publishes = [], [], []
    real_replace = os.replace

    def replace(source, target):
        assert Path(source).parent.parent == tmp_path
        assert Path(target).parent == tmp_path
        assert not any(event[0] in {"done", "log"} for event in events)
        publishes.append((source, target))
        real_replace(source, target)

    monkeypatch.setattr(archives.os, "replace", replace)
    archives.backup_app(PACKAGE, str(tmp_path), 12, **backup_options(events, puller(calls)))
    final = tmp_path / f"backup_{PACKAGE}.zip"
    with zipfile.ZipFile(final) as zf:
        assert set(zf.namelist()) == {"base.apk", "split.apk"}
        assert zf.read("base.apk") == b"/app/base.apk"
    assert len(publishes) == 1
    assert calls[0] == (("shell", f"pm path --user 12 {PACKAGE}"), {})
    assert [args[0] for args, _ in calls] == ["shell", "pull", "pull"]
    assert all(kwargs == {} for _, kwargs in calls)
    assert events == [
        ("progress", PACKAGE, "Fetching APK paths"),
        ("progress", PACKAGE, "Pulling 2 APKs"),
        ("log", f"Backup: {final}"),
        ("done", "backup"),
    ]
    assert list(tmp_path.iterdir()) == [final]


@pytest.mark.parametrize(
    "package,query,expected",
    [
        ("bad;pkg", response(), "Invalid package: bad;pkg"),
        (PACKAGE, response(False, error="offline"), f"Backup failed for {PACKAGE}: offline"),
        (PACKAGE, response(), f"No APK for {PACKAGE}"),
    ],
)
def test_backup_rejects_invalid_package_and_failed_or_empty_path_query(
    tmp_path, package, query, expected
):
    events, calls = [], []

    def execute(*args, **kwargs):
        calls.append(args)
        return query

    archives.backup_app(package, str(tmp_path), 0, **backup_options(events, execute))
    assert events[-1] == ("failure", expected)
    assert len(calls) == (0 if package == "bad;pkg" else 1)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("cancel_at", [None, 1, 2])
def test_backup_pull_failure_is_aggregated_after_remaining_pulls(tmp_path, cancel_at):
    events, calls = [], []
    stopped = False

    def pulled(args, _):
        nonlocal stopped
        index = len(calls) - 1
        stopped = index == cancel_at
        return response(index != 1, error="first pull failed")

    archives.backup_app(
        PACKAGE,
        str(tmp_path),
        0,
        **backup_options(events, puller(calls, on_pull=pulled), lambda: stopped),
    )
    assert len(calls) == (2 if cancel_at == 1 else 3)
    if cancel_at == 1:
        assert events == [
            ("progress", PACKAGE, "Fetching APK paths"),
            ("progress", PACKAGE, "Pulling 2 APKs"),
        ]
    else:
        assert events[-1] == (
            "failure",
            f"Backup failed for {PACKAGE}: 1/2 APK pulls failed; first pull failed",
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("phase", ["progress", "between", "last", "compression"])
def test_backup_cancellation_keeps_phase_specific_feedback(tmp_path, monkeypatch, phase):
    events, calls = [], []
    stopped = False
    old = tmp_path / f"backup_{PACKAGE}.zip"
    old.write_bytes(b"old")
    real_compress = archives.shutil.make_archive

    def progress(*args):
        nonlocal stopped
        events.append(("progress", *args))
        if phase == "progress":
            stopped = True

    def pulled(args, _):
        nonlocal stopped
        if phase == "between" or (phase == "last" and len(calls) == 3):
            stopped = True
        return response()

    def compress(*args):
        nonlocal stopped
        output = real_compress(*args)
        if phase == "compression":
            stopped = True
        return output

    monkeypatch.setattr(archives.shutil, "make_archive", compress)
    options = backup_options(events, puller(calls, on_pull=pulled), lambda: stopped)
    options["progress"] = progress
    archives.backup_app(PACKAGE, str(tmp_path), 0, **options)
    assert len(calls) == {"progress": 1, "between": 2, "last": 3, "compression": 3}[phase]
    assert old.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [old]
    assert not any(event[0] in {"done", "failure"} for event in events)
    if phase in {"last", "compression"}:
        assert events[-2:] == [
            ("log", f"Backup aborted for {PACKAGE}"),
            ("info", f"Backup aborted: {PACKAGE}"),
        ]
    else:
        assert all(event[0] == "progress" for event in events)


@pytest.mark.parametrize(
    "paths,expected",
    [
        (("/app/a.apk", "/app/other.APK"), True),
        (("/app/same.apk", "/other/same.apk"), False),
        (("/app/a.apk", "/app/a.apk"), False),
    ],
)
def test_backup_apk_count_and_case_rules_are_preserved(tmp_path, paths, expected):
    events, calls = [], []
    original = puller(calls, paths)

    def execute(*args, **kwargs):
        outcome = original(*args, **kwargs)
        if args[0] == "pull" and args[1].endswith("other.APK"):
            nested = Path(args[2]) / "nested"
            nested.mkdir()
            (Path(args[2]) / "other.APK").rename(nested / "other.APK")
        return outcome

    archives.backup_app(PACKAGE, str(tmp_path), 0, **backup_options(events, execute))
    assert (events[-1] == ("done", "backup")) == expected
    if not expected:
        assert events[-1] == (
            "failure",
            f"Backup failed for {PACKAGE}: expected 2 APKs, found 1 after pull",
        )


@pytest.mark.parametrize("phase", ["pull", "inner_cleanup", "outer_cleanup"])
def test_backup_exception_scope_and_cleanup_order(tmp_path, monkeypatch, phase):
    events, calls = [], []
    temporary = archives.tempfile.TemporaryDirectory

    class Temporary:
        def __init__(self, *args, **kwargs):
            self.inner = kwargs["prefix"].startswith(".adblab")
            self.context = temporary(*args, **kwargs)

        def __enter__(self):
            return self.context.__enter__()

        def __exit__(self, *args):
            self.context.__exit__(*args)
            if (self.inner and phase == "inner_cleanup") or (
                not self.inner and phase == "outer_cleanup"
            ):
                raise RuntimeError("cleanup failed")

    monkeypatch.setattr(archives.tempfile, "TemporaryDirectory", Temporary)

    def pulled(*_):
        if phase == "pull":
            raise RuntimeError("pull failed")
        return response()

    options = backup_options(events, puller(calls, on_pull=pulled))
    if phase in {"pull", "outer_cleanup"}:
        with pytest.raises(RuntimeError, match="pull failed|cleanup failed"):
            archives.backup_app(PACKAGE, str(tmp_path), 0, **options)
    else:
        archives.backup_app(PACKAGE, str(tmp_path), 0, **options)
    if phase == "inner_cleanup":
        assert events[-1] == ("failure", f"Backup failed for {PACKAGE}: cleanup failed")
        assert (tmp_path / f"backup_{PACKAGE}.zip").is_file()
    elif phase == "outer_cleanup":
        assert events[-1] == ("done", "backup")
    else:
        assert not any(event[0] == "failure" for event in events)


@pytest.mark.parametrize("phase", ["last_pull", "compression"])
def test_backup_cancel_callback_error_inside_compression_is_reported_as_failure(
    tmp_path, monkeypatch, phase
):
    events, calls = [], []
    stopped = False
    original = archives.shutil.make_archive

    def pulled(*_):
        nonlocal stopped
        if phase == "last_pull" and len(calls) == 3:
            stopped = True
        return response()

    def compress(*args):
        nonlocal stopped
        output = original(*args)
        stopped = True
        return output

    def log(_):
        raise RuntimeError("log failed")

    monkeypatch.setattr(archives.shutil, "make_archive", compress)
    options = backup_options(events, puller(calls, on_pull=pulled), lambda: stopped)
    options["log"] = log
    if phase == "last_pull":
        with pytest.raises(RuntimeError, match="log failed"):
            archives.backup_app(PACKAGE, str(tmp_path), 0, **options)
    else:
        archives.backup_app(PACKAGE, str(tmp_path), 0, **options)
        assert events[-1] == ("failure", f"Backup failed for {PACKAGE}: log failed")


@pytest.mark.parametrize(
    "members,name,modes",
    [
        (("one.apk", "two.apk"), "base.apk-backup.zip", ["install", "install"]),
        (("base.apk-folder/one.apk", "two.apk"), "ordinary.zip", ["install", "install"]),
        (("not-base.apk", "two.apk"), "ordinary.zip", ["install", "install"]),
        (("base.apk", "split.apk", "ignored.APK"), "ordinary.zip", ["install-multiple"]),
        (("only.APK",), "ordinary.zip", []),
        (("../escape.apk",), "ordinary.zip", []),
    ],
)
def test_restore_uses_safe_extraction_and_exact_split_basename(
    tmp_path, monkeypatch, members, name, modes
):
    events, calls, extracts = [], [], []
    safe_extract = archives.safe_extract_zip

    def extract(zf, target):
        extracts.append(target)
        return safe_extract(zf, target)

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return response()

    monkeypatch.setattr(archives, "safe_extract_zip", extract)
    archives.restore_apps([archive(tmp_path, members, name)], **restore_options(events, execute))
    assert len(extracts) == 1
    assert [args[0] for args, _ in calls] == modes
    assert all(kwargs == {"timeout": 120} for _, kwargs in calls)
    assert not (tmp_path.parent / "escape.apk").exists()
    assert events[-1] == (
        ("done", "restore") if modes else ("error", "Restore incomplete: 0 succeeded, 1 failed")
    )


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("target", [0, None])
def test_restore_confirms_user_before_every_write_and_accepts_zero(tmp_path, split, target):
    events, order = [], []

    def confirm():
        order.append("confirm")
        return target

    def execute(*args, **kwargs):
        assert args[1:4] == ("--user", "0", "-r")
        assert kwargs == {"timeout": 120}
        order.append("write")
        return response()

    files = [archive(tmp_path, ("base.apk", "split.apk") if split else ("one.apk", "two.apk"))]
    archives.restore_apps(files, **restore_options(events, execute, confirm_user=confirm))
    assert order == (["confirm"] if target is None else ["confirm", "write"] * (1 if split else 2))
    if target is None:
        assert events == []


@pytest.mark.parametrize(
    "phase,installed,completed",
    [
        ("extract", 0, 0),
        ("first", 1, 0),
        ("last", 2, 1),
        ("split", 2, 1),
        ("between", 2, 1),
    ],
)
def test_restore_cancellation_preserves_installed_and_completed_counts(
    tmp_path,
    monkeypatch,
    phase,
    installed,
    completed,
):
    events, calls = [], []
    stopped = False
    extract_original = archives.safe_extract_zip

    def extract(zf, target):
        nonlocal stopped
        extract_original(zf, target)
        if phase == "extract":
            stopped = True

    def execute(*args, **kwargs):
        nonlocal stopped
        calls.append(args)
        if phase in {"first", "split"} or (phase == "last" and len(calls) == 2):
            stopped = True
        return response()

    def log(text):
        nonlocal stopped
        events.append(("log", text))
        if phase == "between" and text.startswith("Restored"):
            stopped = True

    monkeypatch.setattr(archives, "safe_extract_zip", extract)
    options = restore_options(events, execute, lambda: stopped)
    options["log"] = log
    files = [
        archive(tmp_path, ("base.apk", "split.apk") if phase == "split" else ("one.apk", "two.apk"))
    ]
    if phase == "between":
        files.append(archive(tmp_path, name="other.zip"))
    archives.restore_apps(files, **options)
    message = f"Restore cancelled: {installed} APKs installed, {completed} archives completed"
    assert events[-2:] == [("log", message), ("warning", message)]
    assert not any(event[0] == "done" for event in events)
    assert sum(len(args) - 4 if args[0] == "install-multiple" else 1 for args in calls) == installed
    assert (
        sum(event[0] == "log" and event[1].startswith("Restored (") for event in events)
        == completed
    )


def test_restore_partial_failure_continues_next_archive_without_completion(tmp_path):
    events, calls = [], []

    def execute(*args, **kwargs):
        calls.append(args)
        return response(len(calls) != 2, error="install failed")

    archives.restore_apps(
        [archive(tmp_path), archive(tmp_path, ("one.apk",), "other.zip")],
        **restore_options(events, execute),
    )
    assert len(calls) == 3
    assert events[0][0] == "failure"
    assert events[-2:] == [
        ("log", "Restore incomplete: 1 succeeded, 1 failed"),
        ("warning", "Restore incomplete: 1 succeeded, 1 failed"),
    ]


def test_restore_user_probe_cancellation_returns_without_extra_cancel_warning(tmp_path):
    events = []
    stopped = False

    def confirm():
        nonlocal stopped
        stopped = True
        return None

    archives.restore_apps(
        [archive(tmp_path)],
        **restore_options(
            events,
            lambda *args, **kwargs: pytest.fail("unexpected write"),
            lambda: stopped,
            confirm,
        ),
    )
    assert events == []


@pytest.mark.parametrize(
    "phase", ["restored_log", "cleanup", "pre_cancel", "inner_cancel", "failure"]
)
def test_restore_callback_and_cleanup_exceptions_keep_original_try_scope(
    tmp_path, monkeypatch, phase
):
    events = []
    temporary = archives.tempfile.TemporaryDirectory
    cancelled_calls = 0

    class Temporary:
        def __init__(self, *args, **kwargs):
            self.context = temporary(*args, **kwargs)

        def __enter__(self):
            return self.context.__enter__()

        def __exit__(self, *args):
            self.context.__exit__(*args)
            if phase == "cleanup":
                raise RuntimeError("cleanup failed")

    def cancelled():
        nonlocal cancelled_calls
        cancelled_calls += 1
        if (phase == "pre_cancel" and cancelled_calls == 1) or (
            phase == "inner_cancel" and cancelled_calls == 2
        ):
            raise RuntimeError("cancel failed")
        return False

    def log(text):
        events.append(("log", text))
        if phase == "restored_log" and text.startswith("Restored ("):
            raise RuntimeError("log failed")

    def failure(text):
        events.append(("failure", text))
        if phase == "failure":
            raise RuntimeError("failure failed")

    monkeypatch.setattr(archives.tempfile, "TemporaryDirectory", Temporary)
    options = restore_options(events, cancelled=cancelled)
    options.update(log=log, failure=failure)
    files = [archive(tmp_path, ("none.txt",) if phase == "failure" else ("one.apk",))]
    if phase in {"pre_cancel", "failure"}:
        with pytest.raises(RuntimeError, match="cancel failed|failure failed"):
            archives.restore_apps(files, **options)
    else:
        archives.restore_apps(files, **options)
        succeeded = int(phase == "restored_log")
        assert events[-1] == (
            "warning" if succeeded else "error",
            f"Restore incomplete: {succeeded} succeeded, 1 failed",
        )


def test_restore_last_failure_then_cancel_prioritizes_cancel_summary(tmp_path):
    events = []
    stopped = False

    def execute(*args, **kwargs):
        nonlocal stopped
        stopped = True
        return response(False, error="install failed")

    archives.restore_apps(
        [archive(tmp_path, ("one.apk",))], **restore_options(events, execute, lambda: stopped)
    )
    assert events[0][0] == "failure"
    assert events[-1] == ("warning", "Restore cancelled: 0 APKs installed, 0 archives completed")


def test_restore_empty_and_all_failed_have_distinct_terminal_states(tmp_path):
    events = []
    archives.restore_apps([], **restore_options(events))
    assert events == []
    archives.restore_apps(
        [archive(tmp_path, ("one.txt",)), archive(tmp_path, ("two.txt",), "other.zip")],
        **restore_options(events),
    )
    assert sum(event[0] == "failure" for event in events) == 2
    assert events[-2:] == [
        ("log", "Restore incomplete: 0 succeeded, 2 failed"),
        ("error", "Restore incomplete: 0 succeeded, 2 failed"),
    ]
