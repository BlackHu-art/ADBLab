"""把 MobilePerf 生成的 CSV 指标文件汇总为 Excel 报告。"""

import os

from mobileperf.android.excel import Excel
from mobileperf.common.log import logger
from mobileperf.common.utils import TimeUtils


class Report:
    """筛选可汇总的指标文件，并生成带曲线的 Excel 工作簿。"""

    def __init__(self, csv_dir, packages=[]):
        os.chdir(csv_dir)
        # 仅下列 CSV 指标需要生成汇总曲线。
        self.summary_csf_file = {
            "cpuinfo.csv": {
                "table_name": "pid_cpu",
                "x_axis": "datatime",
                "y_axis": "%",
                "values": ["pid_cpu%", "total_pid_cpu%"],
            },
            "meminfo.csv": {
                "table_name": "pid_pss",
                "x_axis": "datatime",
                "y_axis": "mem(MB)",
                "values": ["pid_pss(MB)", "total_pss(MB)"],
            },
            "thread_num.csv": {
                "table_name": "thread_num",
                "x_axis": "datatime",
                "y_axis": "thread_num",
                "values": ["thread_num"],
            },
            "pid_change.csv": {
                "table_name": "pid",
                "x_axis": "datatime",
                "y_axis": "pid_num",
                "values": ["pid"],
            },
        }
        self.packages = packages
        if len(self.packages) > 0:
            for package in self.packages:
                pss_detail_dic = {
                    "table_name": "pss_detail",
                    "x_axis": "datatime",
                    "y_axis": "mem(MB)",
                    "values": ["pss", "java_heap", "native_heap", "system"],
                }
                if ":" in package:
                    # 子进程包名过长会导致 Excel 工作表写入失败，使用末段缩短名称。
                    self.summary_csf_file[f"pss_{package.split(':')[-1].split('.')[-1]}.csv"] = (
                        pss_detail_dic
                    )
                else:
                    self.summary_csf_file[f"pss_{package}.csv"] = pss_detail_dic
        logger.debug(self.packages)
        logger.debug(self.summary_csf_file)
        logger.info(f"create report for {csv_dir}")
        file_names = self.filter_file_names(csv_dir)
        logger.debug(f"{file_names}")
        if file_names:
            book_name = f"summary_{TimeUtils.getCurrentTimeUnderline()}.xlsx"
            excel = Excel(book_name)
            for file_name in file_names:
                logger.debug(f"get csv {file_name} to excel")
                values = self.summary_csf_file[file_name]
                excel.csv_to_xlsx(
                    file_name,
                    values["table_name"],
                    values["x_axis"],
                    values["y_axis"],
                    values["values"],
                )
            logger.info(f"wait to save {book_name}")
            excel.save()

    def filter_file_names(self, device):
        """返回目录中存在且已配置汇总规则的 CSV 文件名。"""
        csv_files = []
        logger.debug(device)
        for f in os.listdir(device):
            if (
                os.path.isfile(os.path.join(device, f))
                and os.path.basename(f) in self.summary_csf_file.keys()
            ):
                logger.debug(os.path.join(device, f))
                csv_files.append(f)
        return csv_files


if __name__ == "__main__":
    # 根据 CSV 生成 Excel 汇总文件。
    from mobileperf.android.globaldata import RuntimeData

    RuntimeData.packages = [
        "com.alibaba.ailabs.genie.smartapp",
        "com.alibaba.ailabs.genie.smartapp:core",
        "com.alibaba.ailabs.genie.smartapp:business",
    ]
    RuntimeData.package_save_path = (
        "/Users/look/Downloads/mobileperf-turandot-shicun-2-13/results/"
        "com.alibaba.ailabs.genie.smartapp/2020_02_13_22_58_14"
    )
    report = Report(RuntimeData.package_save_path, RuntimeData.packages)
    report.filter_file_names(RuntimeData.package_save_path)
