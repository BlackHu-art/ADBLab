#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
 @author         :  Frankie
 @description : 用配置文件替代了
 @time             :  2023/10/14  22:20
 """
import os


class PathTool(object):

    @staticmethod
    def get_project_path():
        """
        @Description：获取当前项目的根目录路径
        """
        Project_Path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return Project_Path

    @staticmethod
    def get_splicing_path(join_path):
        """
        从根目录下开始拼接出其他路径
        """
        if not isinstance(join_path, (str, os.PathLike)):
            raise ValueError("join_path 必须是字符串或 PathLike 对象")

        project_path = PathTool.get_project_path()
        if not isinstance(project_path, str):
            raise TypeError("project_path 必须是字符串")

        try:
            # 使用 os.path.join 进行路径拼接
            filepath = os.path.join(project_path, join_path)
            # 规范化路径
            filepath = os.path.normpath(filepath)
            # 确保路径绝对化
            filepath = os.path.abspath(filepath)
        except Exception as e:
            raise ValueError(f"路径拼接失败: {e}")

        return filepath

    @staticmethod
    def get_full_path(join_path):
        """
        从根目录下开始拼接出其他路径，并返回文件目录的结构，包括路径、目录名称、文件名称
        """
        if not isinstance(join_path, (str, os.PathLike)):
            raise ValueError("join_path 必须是字符串或 PathLike 对象")

        project_path = PathTool.get_project_path()
        if not isinstance(project_path, str):
            raise TypeError("project_path 必须是字符串")

        try:
            # 拼接完整路径
            full_path = os.path.join(project_path, join_path)
            full_path = os.path.normpath(full_path)
            full_path = os.path.abspath(full_path)

            # 使用 os.walk 遍历目录，返回路径、目录名称、文件名称
            if os.path.isdir(full_path):
                # os.walk returns a generator of tuples: (dirPath, dirNames, fileNames)
                return os.walk(full_path)
            else:
                raise NotADirectoryError(f"{full_path} 不是有效的目录路径")

        except Exception as e:
            raise ValueError(f"路径拼接失败: {e}")

    @staticmethod
    def get_desktop_dir():
        """
        @Description: 获取用户桌面路径
        """
        return os.path.join(os.path.expanduser('~'), 'Desktop')

    @staticmethod
    def get_current_file_path():
        """
        @Description：获取当前文件路径
        """
        current_working_dir = os.getcwd()
        # print(f"当前工作路径: {current_working_dir}")
        return current_working_dir

    @staticmethod
    def get_config_dir():
        """
        @Description：获取配置文件路径
        """
        config_dir = path_tool.get_splicing_path('\\config\\')
        return config_dir


path_tool = PathTool()

if __name__ == '__main__':
    print(path_tool.get_project_path())
    print(path_tool.get_splicing_path(join_path='\\config\\'))
    print(path_tool.get_desktop_dir())
    print(path_tool.get_current_file_path())
    # print(path.get_splicing_path("/logs"))
    # print(path.get_desktop_dir())
    # print(path.get_current_file_path())
