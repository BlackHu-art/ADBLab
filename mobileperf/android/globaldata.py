# -*- coding: utf-8 -*-

"""
 @author      :  Frankie
 @time        :  $DATA  $TIME
"""
import threading


# 记录运行时需要共享的全局变量
class RuntimeData():
    # 记录pid变更前的pid
    old_pid = None
    packages = None
    package_save_path = None
    start_time = None
    exit_event = threading.Event()
    top_dir = None
    config_dic = {}
