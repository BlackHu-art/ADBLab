"""无 Qt 查询事务的目标、预算、失败和回调边界。"""

from types import SimpleNamespace

import pytest

from core.exec import CommandResult
from services.app_metadata import AppMetadata, MetadataBatch
from services.apps import queries as q

INVALID_USER = '尚未确认应用所属用户，请刷新应用列表后重试。'
UNKNOWN_USER = '无法确认设备当前用户，请检查设备并刷新应用列表。'
CHANGED_USER = '设备用户已切换，请刷新应用列表后重试。'
DETAIL_FAILURE = 'Failed to read app details; refresh to retry'


class Executor:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, *args, timeout=30, cancellable=False):
        self.calls.append((args, timeout, cancellable))
        response = next(self.responses)
        return response() if callable(response) else response


class DetailRun:
    def __init__(self, executor, budget=5):
        self.now = 100.0
        self.rows, self.logs = [], []
        self.stopped = False
        self.budget_calls = 0
        self.budget = budget
        self.execute = executor

    def query_budget(self):
        self.budget_calls += 1
        return self.budget

    def run(self, packages, **kwargs):
        q.load_package_details(
            packages, execute=self.execute, cancelled=lambda: self.stopped,
            query_budget=self.query_budget, clock=lambda: self.now,
            on_detail=self.rows.append, log=self.logs.append, **kwargs,
        )


def section(index, text='versionName=1.2\nversionCode=7'):
    return f'__ADBLAB_PKG_BEGIN_{index}__\n{text}\n__ADBLAB_PKG_END_{index}__'


@pytest.mark.parametrize('user', [True, False, -1, 2**31, '10', 1.5, object()])
def test_loaded_user_policy_rejects_bool_and_unknown_without_execution(user):
    with pytest.raises(q.QueryError, match=INVALID_USER):
        q.validate_loaded_user(user, required=False)
    with pytest.raises(q.QueryError, match=INVALID_USER):
        q.validate_loaded_user(user, required=True)


def test_loaded_user_optional_none_and_integer_edges():
    q.validate_loaded_user(None, required=False)
    for user in (0, 10, 2**31 - 1):
        q.validate_loaded_user(user, required=True)
    with pytest.raises(q.QueryError, match=INVALID_USER):
        q.validate_loaded_user(None, required=True)


@pytest.mark.parametrize(('output', 'expected'), [
    (' 10\n', 10), ('0', 0), ('2147483647', 2**31 - 1),
    ('2147483648', None), ('00000000000', None), ('１０', None),
    ('10\n0', None), ('-1', None), ('unknown', None), ('', None),
])
def test_current_user_parsing_never_guesses_zero(output, expected):
    assert q.parse_current_user(output) == expected
    execute = Executor(CommandResult(True, output))
    assert q.read_current_user(execute=execute, cancelled=lambda: False, timeout=4.5) == expected
    assert execute.calls == [(('shell', 'am', 'get-current-user'), 4.5, True)]


@pytest.mark.parametrize('success,cancelled', [(False, False), (True, True)])
def test_current_user_failure_or_cancel_is_unknown(success, cancelled):
    assert q.read_current_user(
        execute=Executor(CommandResult(success, '10')), cancelled=lambda: cancelled, timeout=5,
    ) is None


@pytest.mark.parametrize(('expected', 'current', 'message'), [
    (None, None, UNKNOWN_USER), (10, 0, CHANGED_USER), (10, 10, None), (None, 0, None),
])
def test_bind_keeps_expected_user_or_reports_change(expected, current, message):
    calls = []

    def read():
        calls.append('read')
        return current

    if message:
        with pytest.raises(q.QueryError, match=message):
            q.bind_current_user(expected, read_user=read, cancelled=lambda: False)
    else:
        assert q.bind_current_user(expected, read_user=read, cancelled=lambda: False) == current
    assert calls == ['read']
    assert q.bind_current_user(expected, read_user=read, cancelled=lambda: True) is None
    assert calls == ['read', 'read']


@pytest.mark.parametrize('output,expected', [
    ('package:/data/app/base=com.demo\n', [('Demo', 'com.demo', 'Disabled', 'User')]), ('', []),
])
def test_list_requires_both_queries_for_one_user(output, expected):
    execute = Executor(CommandResult(True, output), CommandResult(True, 'package:com.demo'))
    assert q.load_installed_apps(10, execute=execute, cancelled=lambda: False) == expected
    assert execute.calls == [
        (('shell', 'pm', 'list', 'packages', '-f', '--user', '10'), 30, True),
        (('shell', 'pm', 'list', 'packages', '-d', '--user', '10'), 30, True),
    ]


@pytest.mark.parametrize('failed_index', [0, 1])
def test_list_failure_and_cancel_never_return_partial_rows(failed_index):
    responses = [CommandResult(True, 'package:/data/app/base=com.demo'),
                 CommandResult(True, '')]
    responses[failed_index] = CommandResult(False, error='  disconnected  ')
    execute = Executor(*responses)
    message = ('Failed to list apps: disconnected' if failed_index == 0 else
               'Failed to read disabled app states; refresh to retry')
    with pytest.raises(q.QueryError, match=message):
        q.load_installed_apps(10, execute=execute, cancelled=lambda: False)
    assert len(execute.calls) == failed_index + 1
    cancelled = [False]

    def stop():
        cancelled[0] = True
        return CommandResult(True, 'package:/data/app/base=com.demo')

    execute = Executor(*(responses[:failed_index] + [stop]))
    assert q.load_installed_apps(10, execute=execute, cancelled=lambda: cancelled[0]) is None
    assert len(execute.calls) == failed_index + 1


@pytest.mark.parametrize('part', ['details', 'permissions'])
def test_snapshot_reads_once_and_rejects_missing_package(part):
    output = 'codePath=/data/app/demo\nversionCode=7'
    execute = Executor(CommandResult(True, output))
    assert q.read_package_snapshot(
        'com.demo', part, execute=execute, cancelled=lambda: False,
    ) == output
    assert execute.calls == [(('shell', 'dumpsys package com.demo'), 30, True)]
    for result in (CommandResult(False, error='offline'), CommandResult(True, 'not found')):
        with pytest.raises(q.QueryError, match=f'Failed to read app {part}; retry'):
            q.read_package_snapshot(
                'com.demo', part, execute=Executor(result), cancelled=lambda: False,
            )
    execute = Executor()
    with pytest.raises(q.QueryError, match='Invalid package: bad/name'):
        q.read_package_snapshot('bad/name', part, execute=execute, cancelled=lambda: False)
    assert execute.calls == []
    assert q.read_package_snapshot(
        'com.demo', part, execute=Executor(CommandResult(True, output)), cancelled=lambda: True,
    ) is None


def test_detail_fallback_shares_deadline():
    def batch():
        run.now += 4.5
        return CommandResult(True, 'no markers')

    def fallback():
        run.now += 0.5
        return CommandResult(True, 'versionName=1.2\nversionCode=7')

    execute = Executor(batch, fallback)
    run = DetailRun(execute)
    run.run(['com.one', 'com.two'])
    assert execute.calls == [
        (('shell', 'echo __ADBLAB_PKG_BEGIN_0__ ; dumpsys package com.one ; '
          'echo __ADBLAB_PKG_END_0__ ; echo __ADBLAB_PKG_BEGIN_1__ ; '
          'dumpsys package com.two ; echo __ADBLAB_PKG_END_1__'), 5.0, True),
        (('shell', 'dumpsys package com.one'), 0.5, True),
    ]
    assert run.rows == [('com.one', 'one', '1.2 (7)', '')]
    assert run.budget_calls == 1


def test_detail_default_budget_uses_original_package_count():
    execute = Executor(CommandResult(True, section(0) + '\n' + section(1)))
    run = DetailRun(execute)
    run.run(['com.one', 'bad/name', 'com.one'])
    assert execute.calls[0][1:] == (6.0, True)
    assert execute.calls[0][0][1].count('dumpsys package com.one') == 2
    assert run.rows == [('com.one', 'one', '1.2 (7)', '')] * 2
    assert run.logs == ['Invalid package names skipped while reading details', 'Details: 1/2']
    assert run.budget_calls == 1


def test_detail_complete_missing_sections_are_not_retried():
    execute = Executor(CommandResult(True, section(0, 'not installed') + '\n'
                                     + '__ADBLAB_PKG_BEGIN_1__\ntruncated'),
                       CommandResult(True, 'not installed'))
    run = DetailRun(execute)
    run.run(['com.missing', 'com.truncated'])
    assert execute.calls[1] == (('shell', 'dumpsys package com.truncated'), 5, True)
    assert len(execute.calls) == 2
    assert run.rows == []
    assert run.logs == ['Details: 1/2']


@pytest.mark.parametrize('when', ['batch_fail', 'batch_cancel', 'expired', 'fallback_fail',
                                  'fallback_cancel', 'between_callbacks', 'before'])
def test_detail_failure_cancel_and_expiry_stop_retries(when):
    def batch():
        if when == 'batch_cancel':
            run.stopped = True
        if when == 'expired':
            run.now += 5
        if when == 'between_callbacks':
            return CommandResult(True, section(0) + '\n' + section(1))
        if when == 'batch_fail':
            return CommandResult(False, error='offline')
        return CommandResult(True, section(0))

    def fallback():
        if when == 'fallback_cancel':
            run.stopped = True
        return CommandResult(False, error='offline')

    execute = Executor(batch, fallback)
    run = DetailRun(execute)
    if when == 'before':
        run.stopped = True
    if when == 'between_callbacks':
        def publish(row):
            run.rows.append(row)
            run.stopped = True
        publish_callback = publish
        q.load_package_details(
            ['com.one', 'com.two'], execute=execute, cancelled=lambda: run.stopped,
            query_budget=run.query_budget, clock=lambda: run.now,
            on_detail=publish_callback, log=run.logs.append,
        )
    else:
        run.run(['com.one', 'com.two'])
    expected_calls = 0 if when == 'before' else 2 if when.startswith('fallback') else 1
    assert len(execute.calls) == expected_calls
    expected_rows = [] if when in {'before', 'batch_fail', 'batch_cancel'} else [
        ('com.one', 'one', '1.2 (7)', ''),
    ]
    assert run.rows == expected_rows
    assert (DETAIL_FAILURE in run.logs) is (when in {'batch_fail', 'fallback_fail'})
    if when == 'before':
        assert run.budget_calls == 0


def metadata(package='com.one', user=10):
    return AppMetadata(package, '应用', '1.2 (7)', '2026-10-24', 'a' * 64, user)


def run_metadata(run, result, *, elapsed=0, expected_user=None, on_metadata=None):
    rows, errors = [], []

    def loader(device, packages, cancelled):
        assert device == 'synthetic-device' and packages == ['com.one', 'com.two']
        assert not cancelled()
        run.now += elapsed
        return result

    q.load_metadata_with_fallback(
        'synthetic-device', ['com.one', 'com.two'], expected_user=expected_user,
        execute=run.execute, cancelled=lambda: run.stopped,
        query_budget=run.query_budget, clock=lambda: run.now, metadata_loader=loader,
        on_metadata=on_metadata or rows.append, on_detail=run.rows.append,
        log=run.logs.append, failure=errors.append,
    )
    return rows, errors


@pytest.mark.parametrize('elapsed,unsupported,records,expected_calls', [
    (12, True, {}, 1), (31, True, {}, 0), (0, False, {}, 0),
    (0, True, {'com.one': metadata()}, 0), (0, False, {'com.one': metadata()}, 0),
])
def test_metadata_fallback_uses_only_explicit_unsupported_and_remaining_time(
    elapsed, unsupported, records, expected_calls,
):
    execute = Executor(CommandResult(True, section(0) + '\n' + section(1)))
    run = DetailRun(execute)
    rows, errors = run_metadata(run, MetadataBatch(records, unsupported), elapsed=elapsed)
    assert len(execute.calls) == expected_calls
    assert run.budget_calls == expected_calls
    if expected_calls:
        assert execute.calls[0][1:] == (18.0, True)
        assert run.rows == [('com.one', 'one', '1.2 (7)', ''), ('com.two', 'two', '1.2 (7)', '')]
    assert rows == list(records.values())
    assert errors == []


def test_metadata_filters_user_per_record_and_cancels_between_callbacks():
    run = DetailRun(Executor())
    one, two = metadata(user=0), metadata('com.two')
    rows, errors = run_metadata(run, MetadataBatch({'com.one': one, 'com.two': two}),
                                expected_user=10)
    assert rows == [two] and errors == [CHANGED_USER]
    assert run.logs == []
    run = DetailRun(Executor())
    rows = []

    def publish(item):
        rows.append(item)
        run.stopped = True

    run_metadata(run, MetadataBatch({'com.one': one, 'com.two': two}), on_metadata=publish)
    assert rows == [one]
    assert run.logs == []


def test_metadata_none_user_does_not_read_unbound_fixture_identity():
    run = DetailRun(Executor())
    item = SimpleNamespace(
        package='com.one', label='应用', version='', installed='', fingerprint='',
    )
    rows, errors = run_metadata(run, MetadataBatch({'com.one': item}))
    assert rows == [item] and errors == []
    assert run.logs == ['部分应用信息未读取，请刷新重试。']


def test_metadata_loader_errors_propagate_without_fallback():
    execute = Executor()

    def loader(*args):
        raise RuntimeError('loader failed')

    with pytest.raises(RuntimeError, match='loader failed'):
        q.load_metadata_with_fallback(
            'synthetic-device', ['com.one'], expected_user=None, execute=execute,
            cancelled=lambda: False, query_budget=lambda: pytest.fail('unexpected budget'),
            clock=lambda: 100, metadata_loader=loader, on_metadata=lambda row: None,
            on_detail=lambda row: None, log=lambda message: None, failure=lambda message: None,
        )
    assert execute.calls == []
