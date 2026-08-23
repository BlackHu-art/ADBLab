"""提供 MobilePerf 使用的时间、文件和单位换算工具。"""

import os
import time

BaseDir = os.path.dirname(os.path.abspath(__file__))


class TimeUtils:
    UnderLineFormatter = "%Y_%m_%d_%H_%M_%S"
    NormalFormatter = "%Y-%m-%d %H-%M-%S"
    ColonFormatter = "%Y-%m-%d %H:%M:%S"

    # 文件路径要用这个，mac有空格，很麻烦
    @staticmethod
    def getCurrentTimeUnderline():
        return time.strftime(TimeUtils.UnderLineFormatter, time.localtime(time.time()))

    @staticmethod
    def getCurrentTime():
        return time.strftime(TimeUtils.NormalFormatter, time.localtime(time.time()))

    @staticmethod
    def formatTimeStamp(timestamp):
        return time.strftime(TimeUtils.NormalFormatter, time.localtime(timestamp))

    @staticmethod
    def getTimeStamp(time_str, format):
        timeArray = time.strptime(time_str, format)
        # 转换成时间戳
        return time.mktime(timeArray)


class FileUtils:
    @staticmethod
    def makedir(dir):
        if not os.path.exists(dir):
            os.makedirs(dir)

    @staticmethod
    def get_top_dir():
        dir = os.path.dirname(BaseDir)
        path = os.path.dirname(dir)
        return path

    @staticmethod
    def get_FileSize(filePath):
        """
        获取文件的大小,结果保留4位小数，单位为MB
        :param filePath:
        :return:
        """
        fsize = os.path.getsize(filePath)
        fsize = fsize / float(1024 * 1024)
        return round(fsize, 4)


def ms2s(value):
    return round(value / 1000.0, 2)
