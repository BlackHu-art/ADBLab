"""以本地运行清单登记堆转储归属；不从设备公共目录猜测文件所有者。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

_LOCK = threading.RLock()
_TOKEN = re.compile(r"[0-9a-f]{32}")
_PACKAGE = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+(?:\:[A-Za-z0-9_.]+)?")


class HeapOwnership:
    """清单只接受本设备、本结果目录命名空间的工具 UUID 路径。"""

    def __init__(self, result_dir: str, device: str | None):
        self.root = Path(result_dir).resolve()
        self.device = hashlib.sha256(str(device or "default").encode()).hexdigest()
        self.scope = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
        self.path = self.root / f".adblab-heapdumps-{self.device[:24]}.json"

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(data, dict) or data.get("device") != self.device:
            return []
        rows = data.get("files", [])
        if not isinstance(rows, list):
            return []
        return [row for row in rows if self._valid(row)]

    def _valid(self, row) -> bool:
        if not isinstance(row, dict):
            return False
        token, package = row.get("token", ""), row.get("package", "")
        return (
            isinstance(token, str) and _TOKEN.fullmatch(token) is not None
            and isinstance(package, str) and _PACKAGE.fullmatch(package) is not None
            and row.get("path") == self._remote(token)
            and isinstance(row.get("created"), (int, float))
            and isinstance(row.get("pulled"), bool)
        )

    def _remote(self, token: str) -> str:
        return f"/data/local/tmp/adblab-mobileperf-{self.device[:24]}-{self.scope}-{token}.hprof"

    def _write(self, rows: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps({"device": self.device, "files": rows}), encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def reserve(self, package: str) -> str:
        """先持久登记再允许设备命令，异常或取消留下可重试的清理依据。"""
        if _PACKAGE.fullmatch(package) is None:
            raise ValueError("Invalid heap package")
        with _LOCK:
            rows = self._read()
            token = uuid.uuid4().hex
            path = self._remote(token)
            rows.append(dict(
                token=token, package=package, path=path, created=time.time(), pulled=False,
            ))
            self._write(rows)
            return path

    def entries(self, packages=None) -> list[dict]:
        """返回校验后快照；完整包名相等，不使用子串或通配符。"""
        with _LOCK:
            return [row for row in self._read() if packages is None or row["package"] in packages]

    def mark_pulled(self, path: str) -> None:
        """仅在结构化 pull 成功后确认可清理；失败不降低保留要求。"""
        with _LOCK:
            rows = self._read()
            for row in rows:
                if row["path"] == path:
                    row["pulled"] = True
            self._write(rows)

    def remove(self, path: str) -> None:
        """设备确认删除后移除该精确记录。"""
        with _LOCK:
            self._write([row for row in self._read() if row["path"] != path])
