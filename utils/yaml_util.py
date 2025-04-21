import os
import yaml
from threading import Lock

class YamlTool:
    _lock = Lock()

    @staticmethod
    def load_yaml(file_path: str) -> dict:
        if not os.path.exists(file_path):
            return {}
        with YamlTool._lock:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}

    @staticmethod
    def write_yaml(file_path: str, content: dict) -> bool:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with YamlTool._lock:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(content, f)
                return True
            except Exception:
                return False
