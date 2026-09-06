"""保存有界测试结果和命名方案；不迁移旧设置，也不删除测试产物。"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from utils.user_data import user_config_path

KINDS = frozenset({"monkey", "performance"})
STATES = frozenset({"succeeded", "failed", "cancelled", "partial"})
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PARAMETER_BYTES = 16 * 1024


@dataclass(frozen=True)
class RunArtifact:
    """用户主动打开的本地产物；路径不会被解释成 URL 或命令。"""

    label: str
    path: str


@dataclass(frozen=True)
class RunRecord:
    """一次已结束测试的快照；参数不包含设备准入或运行时对象。"""

    run_id: str
    kind: str
    package_name: str
    started_at: float
    finished_at: float
    state: str
    parameters: dict
    artifacts: tuple[RunArtifact, ...] = ()
    device_label: str = ""
    app_version: str = ""
    message: str = ""


@dataclass(frozen=True)
class RunPreset:
    """可重复载入的表单方案；不授予任何设备操作权限。"""

    preset_id: str
    name: str
    kind: str
    parameters: dict
    updated_at: float


def _text(value: object, *, limit: int = 4096, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("记录文本格式无效")
    if required and not value.strip():
        raise ValueError("记录缺少必要信息")
    return value


def _timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("记录时间格式无效")
    # 先比较数值范围，避免超大 JSON 整数在浮点转换时抛出未归一化的异常。
    if not 0 <= value <= 253402300799:
        raise ValueError("记录时间超出范围")
    return float(value)


def copy_parameters(parameters: object) -> dict:
    """验证 JSON 参数并隔离嵌套引用，拒绝旧设备身份和任意运行时对象。"""
    if not isinstance(parameters, dict) or not all(isinstance(k, str) for k in parameters):
        raise ValueError("测试参数必须是对象")
    if {"device_id", "device_ip", "serialnum", "serial_number"} & parameters.keys():
        raise ValueError("方案不能绑定历史设备")
    try:
        raw = json.dumps(parameters, ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > MAX_PARAMETER_BYTES:
            raise ValueError("测试参数过大")
        return json.loads(raw)
    except (TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("测试参数格式无效") from exc


def _record(data: object) -> RunRecord:
    if not isinstance(data, dict):
        raise ValueError("运行记录格式无效")
    kind = _text(data.get("kind"), required=True)
    state = _text(data.get("state"), required=True)
    if kind not in KINDS or state not in STATES:
        raise ValueError("运行类型或状态无效")
    started = _timestamp(data.get("started_at"))
    finished = _timestamp(data.get("finished_at"))
    if finished < started:
        raise ValueError("结束时间早于开始时间")
    artifacts = data.get("artifacts", [])
    if not isinstance(artifacts, (list, tuple)) or len(artifacts) > 32:
        raise ValueError("附件列表无效")
    parsed = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("附件格式无效")
        path = _text(artifact.get("path"), required=True)
        if not Path(path).is_absolute():
            raise ValueError("附件必须使用本地绝对路径")
        parsed.append(RunArtifact(_text(artifact.get("label"), limit=120, required=True), path))
    return RunRecord(
        run_id=_text(data.get("run_id"), limit=200, required=True),
        kind=kind,
        package_name=_text(data.get("package_name"), limit=500),
        started_at=started,
        finished_at=finished,
        state=state,
        parameters=copy_parameters(data.get("parameters")),
        artifacts=tuple(parsed),
        device_label=_text(data.get("device_label", ""), limit=200),
        app_version=_text(data.get("app_version", ""), limit=200),
        message=_text(data.get("message", "")),
    )


def _preset(data: object) -> RunPreset:
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        raise ValueError("测试方案格式无效")
    return RunPreset(
        preset_id=_text(data.get("preset_id"), limit=200, required=True),
        name=_text(data.get("name"), limit=80, required=True).strip(),
        kind=data["kind"],
        parameters=copy_parameters(data.get("parameters")),
        updated_at=_timestamp(data.get("updated_at")),
    )


class RunLibrary:
    """由单个后台队列拥有的结果库；写盘成功才提交内存快照。

    ``path=None`` 用于独立页面和测试的内存库。损坏或未来版本文件不会被
    静默覆盖；加载失败后拒绝写入，保留原文件供恢复。容量淘汰仅移除索引。
    """

    def __init__(self, path: Path | str | None = None, *, capacity: int = 200):
        if not 1 <= capacity <= 200:
            raise ValueError("记录容量必须在 1 到 200 之间")
        self.path = Path(path) if path is not None else None
        self.capacity = capacity
        self._records: tuple[RunRecord, ...] = ()
        self._presets: tuple[RunPreset, ...] = ()
        self._read_only = False

    @classmethod
    def for_user(cls) -> RunLibrary:
        """仅组合根选择正式用户目录；测试可以替换路径且不接触用户记录。"""
        return cls(user_config_path("test_runs.json"))

    @property
    def records(self) -> tuple[RunRecord, ...]:
        return copy.deepcopy(self._records)

    @property
    def presets(self) -> tuple[RunPreset, ...]:
        return copy.deepcopy(self._presets)

    def load(self) -> None:
        """读取有大小上限的已知版本文件；失败时保留磁盘与当前内存。"""
        if self.path is None:
            return
        try:
            with self.path.open("rb") as source:
                raw = source.read(MAX_FILE_BYTES + 1)
        except FileNotFoundError:
            return
        except OSError:
            self._read_only = True
            raise
        try:
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("结果库文件过大")
            data = json.loads(raw)
            if not isinstance(data, dict) or type(data.get("version")) is not int:
                raise ValueError("结果库格式无效")
            if data["version"] != 1:
                raise ValueError("结果库版本不受支持")
            if not isinstance(data.get("runs"), list) or len(data["runs"]) > 200:
                raise ValueError("结果列表格式无效")
            if not isinstance(data.get("presets"), list) or len(data["presets"]) > 50:
                raise ValueError("方案列表格式无效")
            records = tuple(_record(row) for row in data["runs"])
            presets = tuple(_preset(row) for row in data["presets"])
            if len({r.run_id for r in records}) != len(records):
                raise ValueError("运行记录标识重复")
            if len({p.preset_id for p in presets}) != len(presets):
                raise ValueError("方案标识重复")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self._read_only = True
            raise
        self._records = tuple(sorted(records, key=lambda r: r.finished_at, reverse=True))[
            : self.capacity
        ]
        self._presets = presets

    def record_run(self, record: RunRecord) -> None:
        """按运行标识幂等更新，只保留最近记录，不触碰产物文件。"""
        validated = _record(asdict(record))
        rows = [r for r in self._records if r.run_id != validated.run_id]
        rows.append(validated)
        records = tuple(sorted(rows, key=lambda r: r.finished_at, reverse=True))[: self.capacity]
        self._commit(records, self._presets)

    def save_preset(self, name: str, kind: str, parameters: dict) -> None:
        """同类型同名方案原位保存；新名称另存，超过容量时拒绝新增。"""
        name = _text(name, limit=80, required=True).strip()
        previous = next((p for p in self._presets if (p.kind, p.name) == (kind, name)), None)
        if previous is None and len(self._presets) >= 50:
            raise ValueError("已达到 50 个方案，请更新已有方案或删除不再使用的方案")
        preset = _preset(
            dict(
                preset_id=previous.preset_id if previous else uuid.uuid4().hex,
                name=name,
                kind=kind,
                parameters=parameters,
                updated_at=time.time(),
            )
        )
        rows = tuple(p for p in self._presets if p.preset_id != preset.preset_id)
        self._commit(self._records, (*rows, preset))

    def delete_preset(self, preset_id: str) -> None:
        """仅删除指定方案，不改变设置、历史记录或测试文件。"""
        self._commit(self._records, tuple(p for p in self._presets if p.preset_id != preset_id))

    def _commit(self, records: tuple[RunRecord, ...], presets: tuple[RunPreset, ...]) -> None:
        if self._read_only:
            raise ValueError("结果库无法读取，原文件已保留；请检查结果库文件后重新启动")
        data = {
            "version": 1,
            "runs": [asdict(r) for r in records],
            "presets": [asdict(p) for p in presets],
        }
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("结果库达到大小上限，请减少方案或参数内容")
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=self.path.parent, prefix=".runs-", delete=False
                ) as f:
                    temporary = Path(f.name)
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        self._records = records
        self._presets = presets
