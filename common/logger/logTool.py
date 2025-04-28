#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@author      :  Frankie
@description :  loguru 封装类，导入即可直接使用
@time        :    10:14
"""

from functools import wraps
import sys
import datetime
from loguru import logger as loguru_logger
from pathlib import Path
import configparser
from common.pathTool import path_tool

def singleton_class(cls):
    """
    单例模式装饰器
    """
    instances = {}

    @wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance

@singleton_class
class Logger:
    """
    日志封装类，使用 loguru 进行日志记录，支持读取配置文件。
    """

    def __init__(self):
        self.config = self._load_config()
        self.project_path = path_tool.get_project_path()  # 初始化项目路径
        self._setup_logger()  # 初始化日志配置

    @staticmethod
    def _load_config():
        """
        加载日志配置文件 log.ini。
        :return: configparser 对象
        """
        config = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
        ini_path = Path(__file__).parent / 'log.ini'
        try:
            if ini_path.exists():
                config.read(ini_path, encoding="utf-8")
            else:
                loguru_logger.warning(f"配置文件未找到: {ini_path}")
        except Exception as e:
            loguru_logger.error(f"读取配置文件失败: {e}")
        return config

    def _get_log_path(self):
        """
        获取日志文件路径。
        :return: 日志文件的绝对路径
        """
        log_dir = Path(self.project_path) / 'logs'
        log_file = f"{datetime.date.today()}.log"
        log_path = log_dir / log_file

        try:
            log_dir.mkdir(parents=True, exist_ok=True)  # 创建日志目录
        except Exception as e:
            loguru_logger.error(f"创建日志目录失败: {e}")
        return log_path

    def _setup_logger(self):
        """
        配置 loguru 日志输出，包含标准输出和文件输出。
        """
        loguru_logger.remove()

        # 标准输出日志配置
        if self.config.get('StderrLog', 'is_open', fallback='off').lower() == "on":
            loguru_logger.add(
                sys.stderr,
                format=(
                    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                    "<level>{level:<8}</level> | "
                    "{thread.name:<20} | "
                    "<cyan>{module}</cyan>.<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                    "<level>{message}</level>"
                ),
                level=self.config.get('StderrLog', 'level', fallback='INFO'),
            )

        # 文件输出日志配置
        if self.config.get('FileLog', 'is_open', fallback='off').lower() == "on":
            log_path = self._get_log_path()
            loguru_logger.add(
                sink=str(log_path),
                rotation=self.config.get('FileLog', 'rotation', fallback="1 week"),
                retention=self.config.get('FileLog', 'retention', fallback="1 month"),
                compression='zip',
                encoding="utf-8",
                enqueue=True,
                format=(
                    "[{time:YYYY-MM-DD HH:mm:ss}] | {level:<8} | {file}:{module}:{line} | {message}"
                ),
                level=self.config.get('FileLog', 'level', fallback='INFO'),
            )

    @property
    def logger(self):
        """
        获取 loguru logger 实例。
        :return: loguru.logger
        """
        return loguru_logger

# 实例化日志类
logger = Logger().logger

if __name__ == '__main__':
    logger.debug('This is a debug message')
    logger.info('This is an info message')
    logger.warning('This is a warning message')
    logger.error('This is an error message')
    logger.success('This is a success message')
    logger.critical('This is a critical message')