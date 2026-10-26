"""窗口 owner 销毁后，默认监督器不能返回已删除的 QObject。"""

import pytest
import shiboken6

from core.tasks.qt_supervisor import QtTaskSupervisor

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def reset_shared_supervisor():
    QtTaskSupervisor._shared = None
    yield
    QtTaskSupervisor._shared = None


def test_shared_rebuilds_after_bound_owner_is_destroyed(qt_application):
    owner = QtTaskSupervisor()
    QtTaskSupervisor.bind_shared(owner)
    assert QtTaskSupervisor.shared() is owner

    shiboken6.delete(owner)
    qt_application.processEvents()

    replacement = QtTaskSupervisor.shared()
    assert replacement is not owner
    assert shiboken6.isValid(replacement)
