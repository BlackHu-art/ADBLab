"""约束旧内部包退役后生产导入、物理目录及工程检查范围。"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ('controllers', 'models', 'gui', 'services', 'core', 'utils')


def test_production_imports_do_not_use_retired_package():
    paths = [ROOT / 'main.py']
    for name in PRODUCTION_ROOTS:
        paths.extend((ROOT / name).rglob('*.py'))
    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or '']
            if any(name == 'adblab' or name.startswith('adblab.') for name in names):
                violations.append((str(path.relative_to(ROOT)), node.lineno))
    assert violations == [], '生产代码必须直接依赖职责模块'


def test_tooling_uses_existing_responsibility_roots():
    config = json.loads((ROOT / 'pyrightconfig.json').read_text(encoding='utf-8'))
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    for paths in (config['include'], project['tool']['coverage']['run']['source']):
        assert 'adblab' not in paths
        assert {'services', 'core', 'gui'} <= set(paths)
        assert all((ROOT / path).is_dir() for path in paths)


def test_no_replacement_top_level_packages():
    assert not (ROOT / 'application').exists()
    assert not (ROOT / 'qt_adapters').exists()


def test_retired_package_is_physically_absent():
    assert not (ROOT / 'adblab').exists()
    assert not (ROOT / 'adblab.py').exists()
    assert importlib.util.find_spec('adblab') is None
