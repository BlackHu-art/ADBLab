"""应用层的业务操作与资源监督契约。"""

from .cancellation import CancellationError, CancellationToken
from .install_batch import (
    InstallBatchOutcome,
    InstallBatchStart,
    InstallBatchUseCase,
    InstallRequest,
    InstallUnit,
)
from .operations import (
    ConflictingOperationResultError,
    IncompleteOperationError,
    OperationArtifact,
    OperationManager,
    OperationSnapshot,
    OperationState,
    OperationTransitionError,
    OperationUnitResult,
)
from .supervision import (
    StopDisposition,
    SupervisedTaskSnapshot,
    TaskStopResult,
    TaskSupervisor,
    ThreadedShutdownTask,
)

__all__ = [
    "CancellationError",
    "CancellationToken",
    "ConflictingOperationResultError",
    "IncompleteOperationError",
    "InstallBatchOutcome",
    "InstallBatchStart",
    "InstallBatchUseCase",
    "InstallRequest",
    "InstallUnit",
    "OperationArtifact",
    "OperationManager",
    "OperationSnapshot",
    "OperationState",
    "OperationTransitionError",
    "OperationUnitResult",
    "StopDisposition",
    "SupervisedTaskSnapshot",
    "TaskStopResult",
    "TaskSupervisor",
    "ThreadedShutdownTask",
]
