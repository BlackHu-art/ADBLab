# -*- coding: utf-8  -*-

"""
 @author      :  Frankie
 @time        :  $DATA  $TIME
"""

from setuptools import find_packages, setup

setup(
    name='mobileperf',
    version='1.0.0',
    author='look',
    maintainer='look',
    author_email='57280907@qq.com',
    install_requires=[
        "requests",
        "urllib3",
    ],
    description="Python Android mobile perf (support Python3)"
)