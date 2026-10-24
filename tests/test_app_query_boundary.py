"""在独立解释器阻断 Qt 导入后实际运行注入查询。"""

import os
import subprocess
import sys
import textwrap


def test_query_services_execute_with_fake_dependencies_without_qt():
    program = textwrap.dedent('''
        import importlib.abc
        import sys
        from types import SimpleNamespace

        blocked = ('PySide6', 'qfluentwidgets', 'gui', 'models', 'adblab.presentation')

        class Block(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == prefix or fullname.startswith(prefix + '.')
                       for prefix in blocked):
                    raise AssertionError('forbidden import: ' + fullname)

        sys.meta_path.insert(0, Block())
        from services.apps import package_details, queries

        calls = []
        def execute(*args, timeout=30, cancellable=False):
            calls.append((args, timeout, cancellable))
            if 'packages' in args:
                output = 'package:com.demo' if '-d' in args else 'package:/data/app/base=com.demo'
            elif args == ('shell', 'am', 'get-current-user'):
                output = '10'
            elif args[1].startswith('echo '):
                output = ('__ADBLAB_PKG_BEGIN_0__\\nversionName=1.2\\n'
                          'versionCode=7\\n__ADBLAB_PKG_END_0__')
            else:
                output = 'versionName=1.2\\nversionCode=7'
            return SimpleNamespace(success=True, stdout=output, output=output, error='',
                                   returncode=0, outcome='succeeded', stale=False)

        assert queries.read_current_user(execute=execute, cancelled=lambda: False, timeout=5) == 10
        assert queries.load_installed_apps(10, execute=execute, cancelled=lambda: False) == [
            ('Demo', 'com.demo', 'Disabled', 'User')]
        snapshot = queries.read_package_snapshot(
            'com.demo', 'details', execute=execute, cancelled=lambda: False)
        assert snapshot == 'versionName=1.2\\nversionCode=7'
        rows, logs = [], []
        options = dict(execute=execute, cancelled=lambda: False, query_budget=lambda: 5,
                       clock=lambda: 100, on_detail=rows.append, log=logs.append)
        queries.load_package_details(['com.demo'], **options)
        queries.load_metadata_with_fallback(
            'synthetic-device', ['com.demo'], expected_user=None,
            metadata_loader=lambda *args: SimpleNamespace(records={}, unsupported=True),
            on_metadata=lambda row: None, failure=lambda message: None, **options)
        assert rows == [('com.demo', 'demo', '1.2 (7)', '')] * 2
        assert [call[1] for call in calls[-2:]] == [5, 30]
        assert package_details.parse_app_details('com.demo', '')['Package'] == 'com.demo'
        assert not any(name == prefix or name.startswith(prefix + '.')
                       for name in sys.modules for prefix in blocked)
        print('fake-query-boundary-ok')
    ''')
    result = subprocess.run(
        [sys.executable, '-c', program], cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'fake-query-boundary-ok'
