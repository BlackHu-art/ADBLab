import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

_APPLICATION_REFERENCES = []


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """在整个测试进程中保留同一个 QApplication 包装对象。"""
    application = QApplication.instance() or QApplication([])
    _APPLICATION_REFERENCES.append(application)
    yield application
