import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_write_services_import_and_execute_without_qt_or_models(tmp_path):
    script = textwrap.dedent("""
        import importlib.abc
        import sys
        import zipfile
        from pathlib import Path
        from types import SimpleNamespace

        forbidden = ('PySide6', 'qfluentwidgets', 'gui', 'models', 'adblab.presentation')

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == name or fullname.startswith(name + '.') for name in forbidden):
                    raise AssertionError('forbidden import: ' + fullname)

        sys.meta_path.insert(0, Blocker())
        from services.apps import actions, archives

        root = Path(sys.argv[1])
        root.mkdir()
        archives.tempfile.tempdir = str(root)
        events = []
        stopped = False
        fail = False

        def execute(*args, **kwargs):
            if args[0] == 'shell' and args[1].startswith('pm path'):
                output = 'package:/app/base.apk'
            else:
                output = 'Success'
            if args[0] == 'pull':
                (Path(args[2]) / 'base.apk').write_bytes(b'apk')
            return SimpleNamespace(success=not fail, stdout=output, output=output,
                                   error='offline' if fail else '')

        common = dict(execute=execute, log=lambda text: events.append(('log', text)),
                      failure=lambda text: events.append(('failure', text)),
                      completed=lambda text: events.append(('done', text)))
        feedback = lambda *args: events.append(args)
        cancelled = lambda: stopped

        def writes():
            actions.modify_app('enable', 'org.example.app', 0, feedback=feedback, **common)
            actions.launch_app('org.example.app', 0, **common)
            actions.clear_app('org.example.app', 0, permission_denied=lambda: None, **common)
            actions.modify_permission(
                'org.example.app', 'org.example.permission', 'grant', 0, **common)

        def backup():
            archives.backup_app('org.example.app', str(root), 0, cancelled=cancelled,
                                progress=lambda *args: None, feedback=feedback, **common)

        def restore():
            archives.restore_apps([str(archive)], cancelled=cancelled, confirm_user=lambda: 0,
                                  feedback=feedback, **common)

        writes()
        backup()
        archive = root / 'backup_org.example.app.zip'
        assert zipfile.is_zipfile(archive)
        restore()
        assert [value for kind, value in events if kind == 'done'] == [
            'enable', 'launch', 'clear', 'permissions_changed', 'backup', 'restore']

        events.clear()
        fail = True
        writes()
        backup()
        restore()
        assert not any(kind == 'done' for kind, value in events)
        assert sum(kind == 'failure' for kind, value in events) == 5
        assert ('error', 'offline') in events

        events.clear()
        fail = False
        stopped = True
        backup()
        restore()
        assert not any(kind == 'done' for kind, value in events)
        assert events[-1] == (
            'warning', 'Restore cancelled: 0 APKs installed, 0 archives completed')
        assert not any(any(name == block or name.startswith(block + '.') for block in forbidden)
                       for name in sys.modules)
        print('success failure cancellation completed without forbidden imports')
    """)
    env = os.environ.copy()
    for key in (
        "LOCALAPPDATA",
        "APPDATA",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "MOBILEPERF_LOG_DIR",
    ):
        target = tmp_path / key
        target.mkdir()
        env[key] = str(target)
    env["QT_QPA_PLATFORM"] = "offscreen"
    process = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "files")],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert "success failure cancellation completed" in process.stdout
