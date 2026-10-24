"""应用管理的 Android 用户快照、显式目标和切换拒绝契约。"""

import shlex
import zipfile
from types import SimpleNamespace

import pytest

from core.exec import CommandResult
from models import app_manager_worker as module


@pytest.fixture
def device(monkeypatch):
    state = SimpleNamespace(user="10", commands=[], query_success=True)

    def execute(command, **kwargs):
        state.commands.append(command[3:])
        if command[3:] == ["shell", "am", "get-current-user"]:
            return CommandResult(state.query_success, state.user)
        if "packages" in command:
            return CommandResult(True, "" if "-d" in command else
                                 "package:/data/app/demo/base.apk=com.example.app\n")
        return CommandResult(True, "Success")

    monkeypatch.setattr(module.CommandRunner, "run", execute)
    return state


@pytest.mark.parametrize(("operation", "options", "expected"), [
    ("modify_app", {"action": "disable"},
     ["shell", "pm", "disable-user", "--user", "10", "com.example.app"]),
    ("modify_app", {"action": "enable"},
     ["shell", "pm", "enable", "--user", "10", "com.example.app"]),
    ("modify_app", {"action": "uninstall"}, ["uninstall", "--user", "10", "com.example.app"]),
    ("modify_app", {"action": "force_stop"},
     ["shell", "am", "force-stop", "--user", "10", "com.example.app"]),
    ("clear_app", {}, ["shell", "pm", "clear", "--user", "10", "com.example.app"]),
    ("modify_permission", {"action": "grant", "permission": "android.permission.CAMERA"},
     ["shell", "pm", "grant", "--user", "10", "com.example.app", "android.permission.CAMERA"]),
    ("modify_permission", {"action": "revoke", "permission": "android.permission.CAMERA"},
     ["shell", "pm", "revoke", "--user", "10", "com.example.app", "android.permission.CAMERA"]),
])
def test_mutations_use_the_loaded_user_after_revalidation(device, operation, options, expected):
    worker = module.AppManagerWorker(
        "synthetic-device", operation, user_id=10, package_name="com.example.app", **options,
    )
    done = []
    worker.operation_done.connect(done.append)
    worker.run()
    assert device.commands == [["shell", "am", "get-current-user"], expected]
    assert len(done) == 1


def test_list_and_disabled_states_share_one_confirmed_user(device):
    worker = module.AppManagerWorker("synthetic-device", "load_apps")
    events = []
    worker.user_context_loaded.connect(lambda user: events.append(("user", user)))
    worker.apps_loaded.connect(lambda apps: events.append(("apps", apps)))
    worker.run()
    assert device.commands == [
        ["shell", "am", "get-current-user"],
        ["shell", "pm", "list", "packages", "-f", "--user", "10"],
        ["shell", "pm", "list", "packages", "-d", "--user", "10"],
    ]
    assert events == [("user", 10), ("apps", [("App", "com.example.app", "Enabled", "User")])]


@pytest.mark.parametrize("operation", ["clear_app", "permissions", "app_snapshot", "backup_app"])
def test_user_change_rejects_old_snapshot_before_operation(device, operation):
    device.user = "0"
    worker = module.AppManagerWorker(
        "synthetic-device", operation, user_id=10, package_name="com.example.app",
    )
    feedback, done = [], []
    worker.operation_feedback.connect(lambda *args: feedback.append(args))
    worker.operation_done.connect(done.append)
    worker.run()
    assert device.commands == [["shell", "am", "get-current-user"]]
    assert not done and feedback and feedback[-1][0] == "error"
    assert "刷新" in feedback[-1][1]


@pytest.mark.parametrize("user_id", [None, True, -1, "10", 2**31])
def test_mutation_without_valid_loaded_user_never_queries_or_writes(device, user_id):
    worker = module.AppManagerWorker(
        "synthetic-device", "clear_app", user_id=user_id, package_name="com.example.app",
    )
    feedback = []
    worker.operation_feedback.connect(lambda *args: feedback.append(args))
    worker.run()
    assert device.commands == []
    assert feedback and feedback[-1][0] == "error"


@pytest.mark.parametrize("output", ["", "unknown", "10\n0", "-1", "2147483648"])
def test_unreadable_current_user_does_not_fall_back_to_user_zero(device, output):
    device.user = output
    worker = module.AppManagerWorker("synthetic-device", "load_apps")
    rows = []
    worker.apps_loaded.connect(rows.append)
    worker.run()
    assert device.commands == [["shell", "am", "get-current-user"]]
    assert not rows


def test_cancellation_during_user_query_prevents_all_new_commands(monkeypatch):
    worker = module.AppManagerWorker("synthetic-device", "load_apps")
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        worker.abort()
        assert kwargs["cancelled"]()
        return CommandResult(True, "10")

    monkeypatch.setattr(module.CommandRunner, "run", execute)
    rows = []
    worker.apps_loaded.connect(rows.append)
    worker.run()
    assert len(calls) == 1 and not rows


def test_metadata_from_another_user_is_not_published(monkeypatch, device):
    from services.app_metadata import _decode_record
    from tests.test_app_metadata import metadata_line

    record = _decode_record("com.example.app", metadata_line(user=0).split("\t")[2])
    monkeypatch.setattr(module, "load_app_metadata", lambda *a: SimpleNamespace(
        records={record.package: record}, unsupported=False,
    ))
    worker = module.AppManagerWorker(
        "synthetic-device", "load_metadata_batch", user_id=10, packages=[record.package],
    )
    rows = []
    worker.app_metadata_loaded.connect(rows.append)
    worker.run()
    assert rows == []


def test_launch_uses_explicit_user_instead_of_implicit_monkey_target(device):
    worker = module.AppManagerWorker(
        "synthetic-device", "launch_app", user_id=10, package_name="com.example.app",
    )
    worker.run()
    command = device.commands[-1]
    assert command[:3] == ["shell", "am", "start"]
    assert command[command.index("--user") + 1] == "10"
    assert command[command.index("-p") + 1] == "com.example.app"
    assert "android.intent.category.LAUNCHER" in command


@pytest.mark.parametrize("split", [False, True])
def test_restore_targets_loaded_user_and_stops_after_user_changes(
    device, monkeypatch, tmp_path, split,
):
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("base.apk" if split else "one.apk", b"apk")
        handle.writestr("split.apk" if split else "two.apk", b"apk")
    execute = module.CommandRunner.run

    def switch_after_install(command, **kwargs):
        result = execute(command, **kwargs)
        if command[3] in {"install", "install-multiple"}:
            device.user = "0"
        return result

    monkeypatch.setattr(module.CommandRunner, "run", switch_after_install)
    worker = module.AppManagerWorker(
        "synthetic-device", "restore_apps", user_id=10, file_paths=[str(archive)],
    )
    worker.run()
    installs = [args for args in device.commands if args[0] in {"install", "install-multiple"}]
    assert len(installs) == 1
    assert installs[0][0] == ("install-multiple" if split else "install")
    assert installs[0][1:4] == ["--user", "10", "-r"]


def test_invalid_permission_is_not_sent_to_device(device):
    worker = module.AppManagerWorker(
        "synthetic-device", "modify_permission", user_id=10,
        package_name="com.example.app", permission="User 10:", action="grant",
    )
    worker.run()
    assert not any("grant" in args for args in device.commands)


@pytest.mark.parametrize("permission", [
    "com.example.permission.READ-FOO",
    "com.example.permission.READ$FOO",
    "com.example.permission.读取",
])
def test_custom_permission_name_reaches_device_as_one_literal_argument(device, permission):
    worker = module.AppManagerWorker(
        "synthetic-device", "modify_permission", user_id=10,
        package_name="com.example.app", permission=permission, action="grant",
    )
    done = []
    worker.operation_done.connect(done.append)
    worker.run()
    assert done == ["permissions_changed"]
    command = device.commands[-1]
    assert command[:6] == ["shell", "pm", "grant", "--user", "10", "com.example.app"]
    assert shlex.split(" ".join(command[1:])) == [
        "pm", "grant", "--user", "10", "com.example.app", permission,
    ]
    if "$" in permission:
        assert command[-1] == "'com.example.permission.READ$FOO'"


def test_snapshot_permissions_use_the_same_bound_user_as_the_write_target(device, monkeypatch):
    from tests.test_app_permissions import _PACKAGE

    execute = module.CommandRunner.run

    def snapshot(command, **kwargs):
        if command[3:] == ["shell", "dumpsys package com.example.app"]:
            device.commands.append(command[3:])
            return CommandResult(True, _PACKAGE)
        return execute(command, **kwargs)

    monkeypatch.setattr(module.CommandRunner, "run", snapshot)
    worker = module.AppManagerWorker(
        "synthetic-device", "app_snapshot", user_id=10, package_name="com.example.app",
    )
    permissions, users = [], []
    worker.permissions_loaded.connect(lambda *parts: permissions.append(parts))
    worker.user_context_loaded.connect(users.append)
    worker.run()
    assert users == [10]
    assert len(permissions[0][1]) == 2
    assert permissions[0][2] == [("android.permission.CAMERA", True)]
    assert device.commands == [
        ["shell", "am", "get-current-user"], ["shell", "dumpsys package com.example.app"],
    ]


def test_two_device_workers_keep_separate_user_targets(monkeypatch):
    calls = []
    users = {"synthetic-one": 10, "synthetic-two": 11}

    def execute(command, **kwargs):
        calls.append(command)
        return CommandResult(True, str(users[command[2]]))

    monkeypatch.setattr(module.CommandRunner, "run", execute)
    for device_id, user in users.items():
        module.AppManagerWorker(
            device_id, "clear_app", user_id=user, package_name="com.example.app",
        ).run()
    writes = [command for command in calls if "clear" in command]
    assert [(command[2], command[-2]) for command in writes] == list(
        (device_id, str(user)) for device_id, user in users.items()
    )


def test_launch_error_output_never_reports_success(device, monkeypatch):
    execute = module.CommandRunner.run

    def reject(command, **kwargs):
        if command[3:6] == ["shell", "am", "start"]:
            return CommandResult(True, "Error: Activity not started, unable to resolve Intent")
        return execute(command, **kwargs)

    monkeypatch.setattr(module.CommandRunner, "run", reject)
    worker = module.AppManagerWorker(
        "synthetic-device", "launch_app", user_id=10, package_name="com.example.app",
    )
    done, feedback = [], []
    worker.operation_done.connect(done.append)
    worker.operation_feedback.connect(lambda *args: feedback.append(args))
    worker.run()
    assert not done and feedback and feedback[-1][0] == "error"


def test_failed_user_query_publishes_no_successful_snapshot(device):
    device.query_success = False
    worker = module.AppManagerWorker("synthetic-device", "load_apps")
    events = []
    worker.user_context_loaded.connect(events.append)
    worker.apps_loaded.connect(events.append)
    worker.run()
    assert not events and device.commands == [["shell", "am", "get-current-user"]]


def test_launch_zero_exit_stderr_failure_is_retained_at_command_boundary(device, monkeypatch):
    from core.exec import ExecutionResult, _normalise_result

    execute = module.CommandRunner.run

    def android_shell(command, **kwargs):
        if command[3:6] == ["shell", "am", "start"]:
            output = b"Starting: Intent\n"
            error = b"Error: Activity not started, unable to resolve Intent\n"
            if command[-1] == "2>&1":
                output, error = output + error, b""
            return _normalise_result(ExecutionResult(output, error, 0), kwargs["timeout"])
        return execute(command, **kwargs)

    monkeypatch.setattr(module.CommandRunner, "run", android_shell)
    worker = module.AppManagerWorker(
        "synthetic-device", "launch_app", user_id=10, package_name="com.example.app",
    )
    done, feedback = [], []
    worker.operation_done.connect(done.append)
    worker.operation_feedback.connect(lambda *args: feedback.append(args))
    worker.run()
    assert not done and feedback and feedback[-1][0] == "error"


def test_launch_existing_task_warning_still_reports_success(device, monkeypatch):
    execute = module.CommandRunner.run

    def existing_task(command, **kwargs):
        if command[3:6] == ["shell", "am", "start"]:
            return CommandResult(
                True,
                "Starting: Intent\n"
                "Warning: Activity not started, its current task has been brought to the front\n",
            )
        return execute(command, **kwargs)

    monkeypatch.setattr(module.CommandRunner, "run", existing_task)
    worker = module.AppManagerWorker(
        "synthetic-device", "launch_app", user_id=10, package_name="com.example.app",
    )
    done, feedback = [], []
    worker.operation_done.connect(done.append)
    worker.operation_feedback.connect(lambda *args: feedback.append(args))
    worker.run()
    assert done == ["launch"] and feedback[-1][0] == "success"

@pytest.mark.parametrize(('operation', 'cancel_at', 'expected'), [
    ('load_apps', None, ['user', 'apps']),
    ('load_apps', 'user', ['user', 'apps']),
    ('app_snapshot', None, ['user', 'details', 'permissions']),
    ('app_snapshot', 'user', ['user']),
    ('app_snapshot', 'details', ['user', 'details']),
    ('app_details', None, ['user', 'details']),
    ('permissions', None, ['user', 'permissions']),
])
def test_query_signal_order_and_cancellation_boundaries(
    monkeypatch, operation, cancel_at, expected,
):
    worker = module.AppManagerWorker(
        'synthetic-device', operation, user_id=10, package_name='com.example.app',
    )
    events, logs = [], []

    def event(name):
        events.append(name)
        if name == cancel_at:
            worker.abort()

    worker.user_context_loaded.connect(lambda user: event('user'))
    worker.apps_loaded.connect(lambda apps: event('apps'))
    worker.app_details_loaded.connect(lambda details: event('details'))
    worker.permissions_loaded.connect(lambda *parts: event('permissions'))
    worker.log_message.connect(logs.append)
    monkeypatch.setattr(worker, '_read_current_user', lambda: 10)
    commands = []

    def execute(*args, **kwargs):
        commands.append(args)
        if 'packages' in args:
            return CommandResult(True, '' if '-d' in args else
                                 'package:/data/app/base=com.example.app')
        return CommandResult(True, 'versionCode=7')

    monkeypatch.setattr(worker, '_adb', execute)
    worker.run()
    assert events == expected
    if operation == 'load_apps':
        assert logs == ['Fetching installed apps...', 'Loaded 1 apps.']
        assert len(commands) == 2
    else:
        assert commands == [('shell', 'dumpsys package com.example.app')]


def test_list_keeps_loaded_log_when_cancelled_during_parsing(monkeypatch):
    worker = module.AppManagerWorker('synthetic-device', 'load_apps', user_id=10)
    logs, rows = [], []
    worker.log_message.connect(logs.append)
    worker.apps_loaded.connect(rows.append)

    class CancelDuringSplit(str):
        def splitlines(self):
            worker.abort()
            return super().splitlines()

    results = iter([
        SimpleNamespace(success=True, stdout=CancelDuringSplit('package:/data/app/base=com.demo'),
                        error='', output='', returncode=0, outcome='succeeded', stale=False),
        CommandResult(True, ''),
    ])
    monkeypatch.setattr(worker, '_adb', lambda *args, **kwargs: next(results))
    worker._load_apps()
    assert logs == ['Fetching installed apps...', 'Loaded 1 apps.']
    assert rows == []


@pytest.mark.parametrize('operation', [
    'load_metadata_batch', 'load_icon_batch', 'load_detail_batch',
])
@pytest.mark.parametrize('user_id', [None, 10, True])
def test_batch_operations_skip_current_user_query(monkeypatch, operation, user_id):
    worker = module.AppManagerWorker(
        'synthetic-device', operation, user_id=user_id, packages=['com.example.app'],
    )
    commands, deliveries, errors = [], [], []
    worker.operation_feedback.connect(lambda *args: errors.append(args))
    worker.app_metadata_loaded.connect(lambda row: deliveries.append('metadata'))
    worker.app_icon_loaded.connect(lambda *args: deliveries.append('icon'))
    worker.app_detail_batch.connect(lambda *args: deliveries.append('detail'))
    monkeypatch.setattr(worker, '_read_current_user',
                        lambda: pytest.fail('batch 不得读取当前用户'))

    def execute(*args, **kwargs):
        commands.append(args)
        return CommandResult(True, '__ADBLAB_PKG_BEGIN_0__\nversionCode=7\n__ADBLAB_PKG_END_0__')

    def icons(device, packages, cancelled, emit, **options):
        emit('com.example.app', b'fake-icon', 'a' * 64)

    monkeypatch.setattr(worker, '_adb', execute)
    monkeypatch.setattr(module, 'load_app_icons', icons)
    monkeypatch.setattr(module, 'load_app_metadata', lambda *args: SimpleNamespace(
        records={'com.example.app': SimpleNamespace(
            package='com.example.app', label='应用', version='', installed='',
            fingerprint='a' * 64, user_id=10,
        )}, unsupported=False,
    ))
    worker.run()
    if user_id is True:
        assert deliveries == commands == []
        assert errors == [('error', '尚未确认应用所属用户，请刷新应用列表后重试。')]
    else:
        assert deliveries == [{'load_metadata_batch': 'metadata', 'load_icon_batch': 'icon',
                               'load_detail_batch': 'detail'}[operation]]
        assert not errors
        assert len(commands) == int(operation == 'load_detail_batch')


def test_list_failure_callback_keeps_original_outer_exception_scope(monkeypatch):
    worker = module.AppManagerWorker('synthetic-device', 'load_apps', user_id=10)
    errors = []
    monkeypatch.setattr(
        worker, '_adb', lambda *args, **kwargs: CommandResult(False, error='offline'),
    )

    def failure(message):
        errors.append(message)
        if len(errors) == 1:
            raise RuntimeError('feedback failed')

    monkeypatch.setattr(worker, '_report_failure', failure)
    worker._load_apps()
    assert errors == ['Failed to list apps: offline', 'Error: feedback failed']


@pytest.mark.parametrize('fallback', [False, True])
def test_detail_parsing_cancellation_keeps_current_delivery_and_stops_next(monkeypatch, fallback):
    from services.apps import queries

    worker = module.AppManagerWorker(
        'synthetic-device', 'load_detail_batch', packages=['com.one', 'com.two'],
    )
    rows, commands = [], []
    worker.app_detail_batch.connect(lambda *args: rows.append(args))
    parse = queries.parse_batch_detail

    def parse_then_cancel(package, output):
        worker.abort()
        return parse(package, output)

    def execute(*args, **kwargs):
        commands.append(args)
        if len(commands) == 1 and fallback:
            return CommandResult(True, 'no markers')
        return CommandResult(True, (
            '__ADBLAB_PKG_BEGIN_0__\nversionName=1.2\nversionCode=7\n__ADBLAB_PKG_END_0__\n'
            '__ADBLAB_PKG_BEGIN_1__\nversionName=1.2\nversionCode=7\n__ADBLAB_PKG_END_1__'
        ))

    monkeypatch.setattr(queries, 'parse_batch_detail', parse_then_cancel)
    monkeypatch.setattr(worker, '_adb', execute)
    worker.run()
    assert rows == [('com.one', 'one', '1.2 (7)', '')]
    assert len(commands) == (2 if fallback else 1)
