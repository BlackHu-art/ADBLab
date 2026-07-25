"""应用层的业务操作与资源监督契约。"""

from .cancellation import CancellationError, CancellationToken
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
