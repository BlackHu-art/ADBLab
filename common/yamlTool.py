#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
 @author      :  Frankie
 @description :  遍历config文件夹内全部yaml文件获取配置数据
 @time        :  2023/10/18 17:13
"""

import os
from ruamel.yaml import YAML
from common.logger.logTool import logger
from common.pathTool import PathTool


class YamlTool:
    def __init__(self, file_path):
        self.file_path = PathTool.get_splicing_path(file_path)
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.data = self._load_yaml()

    def _load_yaml(self):
        """加载 YAML 文件内容"""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = self.yaml.load(f)
                    if data is None:
                        data = {}  # 确保返回空字典而不是 None
                    # logger.info(f"加载YAML文件成功: {self.file_path}")
                    return data
            else:
                logger.error(f"文件不存在: {self.file_path}")
                return {}  # 返回空字典
        except Exception as ex:
            logger.error(f"加载YAML文件失败: {ex}")
            return {}  # 遇到异常时也返回空字典

    def save_yaml(self):
        """保存 YAML 数据"""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                self.yaml.dump(self.data, f)
            # logger.info(f"保存YAML文件成功: {self.file_path}")
        except Exception as ex:
            logger.error(f"保存YAML文件失败: {ex}")

    def get(self, key, default=None):
        """获取 YAML 中的值"""
        value = self.data.get(key, default)
        logger.info(f"获取键 {key} 的值: {value}")
        return value

    def add(self, key, value):
        """添加键值对到 YAML"""
        self.data[key] = value
        self.save_yaml()
        logger.info(f"添加键值对: {key} = {value}")

    def update(self, key, value):
        """更新 YAML 文件中的值"""
        if key in self.data:
            self.data[key] = value
            self.save_yaml()
            logger.info(f"更新键 {key} = {value}")
        else:
            logger.warning(f"键 {key} 不存在")

    def delete(self, key):
        """删除 YAML 中的键"""
        if key in self.data:
            del self.data[key]
            self.save_yaml()
            logger.info(f"删除键 {key}")
        else:
            logger.warning(f"键 {key} 不存在")

    def get_nested_value(self, parent_key, child_key):
        """获取嵌套字典中的值"""
        parent_value = self.data.get(parent_key)
        if isinstance(parent_value, dict):
            child_value = parent_value.get(child_key)
            logger.info(f"获取嵌套键 {parent_key}.{child_key} 的值: {child_value}")
            return child_value
        else:
            logger.error(f"父键 {parent_key} 不存在或不是字典类型")
            return None

    def update_nested_value(self, parent_key, child_key, new_value):
        """更新嵌套字典中的值"""
        parent_value = self.data.get(parent_key)

        if isinstance(parent_value, dict):
            # 将新值转换为字符串，以保留前导零
            new_value_str = str(new_value)
            parent_value[child_key] = new_value_str
            self.save_yaml()
            logger.info(f"更新嵌套键 {parent_key}.{child_key} 的值为: {new_value_str}")
        elif isinstance(parent_value, str):
            # 如果 parent_value 是字符串，记录警告日志并返回
            logger.warning(f"父键 {parent_key} 是字符串类型，无法更新子键 {child_key}")
        else:
            logger.error(f"父键 {parent_key} 不存在或不是字典类型")

    def display(self):
        """打印 YAML 数据"""
        return self.data


# 调用示例
if __name__ == '__main__':
    yaml_tool = YamlTool('test_data/doozy_tv/accountInfo.yaml')

    # 获取值
    desired_caps = yaml_tool.get("desired_caps_poco")

    # 添加新键值对
    yaml_tool.add("new_key", "new_value")

    # 更新键值对
    yaml_tool.update("desired_caps_poco", {"platformVersion": "10"})

    # 删除键
    yaml_tool.delete("new_key")

    # 获取嵌套值
    platform_version = yaml_tool.get_nested_value('desired_caps_poco', 'platformVersion')

    # 更新嵌套值
    yaml_tool.update_nested_value('desired_caps_poco', 'platformVersion', '11')

    # 打印全部数据
    all_data = yaml_tool.display()
    print(all_data)
