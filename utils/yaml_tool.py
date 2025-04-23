import os
import threading
import yaml
from threading import Lock
from typing import Dict, Any, Optional
from pathlib import Path


class YamlTool:
    """线程安全的YAML文件操作工具类，支持原子读写"""
    
    _lock = Lock()
    
    @staticmethod
    def load_yaml(file_path: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        安全加载YAML文件
        参数:
            file_path: 文件路径
            default: 当文件不存在或读取失败时返回的默认值
        返回:
            解析后的字典数据，失败时返回default或空字典
        """
        if default is None:
            default = {}
            
        if not os.path.exists(file_path):
            return default.copy()
            
        with YamlTool._lock:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    return data if isinstance(data, dict) else default.copy()
            except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
                print(f"Failed to load YAML {file_path}: {str(e)}")
                return default.copy()

    @staticmethod
    def write_yaml(file_path: str, content: Dict[str, Any], *, 
                  ensure_dir: bool = True, atomic: bool = True) -> bool:
        """
        安全写入YAML文件
        参数:
            file_path: 文件路径
            content: 要写入的字典数据
            ensure_dir: 是否自动创建父目录
            atomic: 是否使用原子写入（临时文件+重命名）
        返回:
            是否成功写入
        """
        if not isinstance(content, dict):
            raise ValueError("Content must be a dictionary")
            
        try:
            if ensure_dir:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
            with YamlTool._lock:
                if atomic:
                    # 原子写入模式
                    temp_path = f"{file_path}.tmp"
                    try:
                        with open(temp_path, "w", encoding="utf-8") as f:
                            yaml.safe_dump(content, f, allow_unicode=True, sort_keys=False)
                        os.replace(temp_path, file_path)  # 原子替换
                        return True
                    except Exception as e:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                        raise
                else:
                    # 直接写入模式
                    with open(file_path, "w", encoding="utf-8") as f:
                        yaml.safe_dump(content, f, allow_unicode=True, sort_keys=False)
                    return True
        except (OSError, yaml.YAMLError) as e:
            print(f"Failed to write YAML {file_path}: {str(e)}")
            return False

    @staticmethod
    def update_yaml(file_path: str, updates: Dict[str, Any], 
                   *, merge_nested: bool = True) -> bool:
        """
        更新YAML文件内容（读取-修改-写入）
        参数:
            file_path: 文件路径
            updates: 要更新的键值对
            merge_nested: 是否深度合并嵌套字典
        返回:
            是否成功更新
        """
        existing = YamlTool.load_yaml(file_path)
        
        if merge_nested:
            YamlTool._deep_update(existing, updates)
        else:
            existing.update(updates)
            
        return YamlTool.write_yaml(file_path, existing)

    @staticmethod
    def _deep_update(original: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """深度合并两个字典"""
        for key, value in updates.items():
            if (key in original and isinstance(original[key], dict) 
                    and isinstance(value, dict)):
                YamlTool._deep_update(original[key], value)
            else:
                original[key] = value
    
    @staticmethod
    def atomic_update(file_path: str, new_data: dict):
        """线程安全的YAML更新"""
        with threading.Lock():
            existing = YamlTool.load_yaml(file_path) or {}
            existing.update(new_data)
            YamlTool.write_yaml(file_path, existing)