"""在内存中对照本轮之前的日志页面，定位多页面 Qt 销毁异常。"""
import importlib.util
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
if '--before' in sys.argv or '--before-all' in sys.argv:
    names = ('gui.dialogs.live_logcat_form', 'gui.dialogs.live_logcat')
    if '--before-all' in sys.argv:
        names = ('gui.generated.translations_rc', 'gui.dialogs.screenshot_viewer_ui',
                 'gui.features.media', 'gui.pages.device_hub', *names)
    for name in names:
        path = Path(__file__).parent / (name.replace('.', '__') + '.py')
        if name == 'gui.pages.device_hub':
            path = Path(__file__).parent / 'device_hub.baseline.py'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
import pytest
raise SystemExit(pytest.main(['-q', 'tests/test_feature_typography.py::test_loaded_feature_pages_refresh_fonts_and_text_constraints']))
