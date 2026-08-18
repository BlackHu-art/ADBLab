"""定义 MobilePerf 监控器的基础接口。"""

import logging

logger = logging.getLogger(__name__)


class Monitor:
    """性能测试数据采集能力基类。"""

    def __init__(self, **kwargs):
        """初始化监控器。

        :param dict kwargs: 配置项
        """
        self.config = kwargs
        self.matched_data = {}

    def start(self):
        """由子类实现开始采集的具体行为。"""
        logger.warn("请在%s类中实现start方法" % type(self))

    def clear(self):
        """清空监控器保存的数据。"""
        self.matched_data = {}

    def stop(self):
        """由子类停止采集，并在需要后续解析时保存数据文件。"""
        logger.warn("请在%s类中实现stop方法" % type(self))

    def save(self):
        """由子类实现数据保存行为。"""
        logger.warn("请在%s类中实现save方法" % type(self))


if __name__ == "__main__":
    pass
