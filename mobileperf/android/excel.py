"""将性能采集 CSV 数据写入 Excel 工作簿并生成趋势图。"""

import csv
import os
import re

from mobileperf.common.log import logger
from mobileperf.extlib import xlsxwriter

_INVALID_WORKSHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_WORKSHEET_NAME_LIMIT = 31


class Excel:
    """封装工作簿、工作表名称归一化和趋势图生成。"""

    def __init__(self, excel_file):
        self.excel_file = excel_file
        self.workbook = xlsxwriter.Workbook(excel_file)
        self.color_list = ["blue", "green", "red", "yellow", "purple"]
        self._worksheet_names = set()

    def _safe_sheet_name(self, sheet_name):
        """返回符合 Excel 限制且在当前工作簿内唯一的工作表名称。"""
        raw_name = str(sheet_name or "Sheet")
        clean_name = _INVALID_WORKSHEET_CHARS.sub("_", raw_name).strip("'").strip()
        base_name = (clean_name or "Sheet")[:_WORKSHEET_NAME_LIMIT]
        candidate = base_name
        suffix_index = 1

        while candidate.lower() in self._worksheet_names:
            suffix = f"_{suffix_index}"
            keep = _WORKSHEET_NAME_LIMIT - len(suffix)
            candidate = (
                f"{base_name[:keep]}{suffix}" if keep > 0 else suffix[-_WORKSHEET_NAME_LIMIT:]
            )
            suffix_index += 1

        self._worksheet_names.add(candidate.lower())
        if candidate != raw_name:
            logger.debug(f"worksheet name normalized: {raw_name} -> {candidate}")
        return candidate

    def add_sheet(self, sheet_name, x_axis, y_axis, headings, lines):
        """写入二维数据，并在数据量足够时插入折线图。"""
        worksheet_name = self._safe_sheet_name(sheet_name)
        worksheet = self.workbook.add_worksheet(worksheet_name)
        worksheet.write_row("A1", headings)
        for i, line in enumerate(lines, 2):
            worksheet.write_row(f"A{i:d}", line)
        columns = len(headings)
        rows = len(lines)
        if columns > 1 and rows > 1:
            chart = self.workbook.add_chart({"type": "line"})
            for j in range(1, columns):
                chart.add_series(
                    {
                        "name": [worksheet_name, 0, j],
                        "categories": [worksheet_name, 1, 0, rows, 0],
                        "values": [worksheet_name, 1, j, rows, j],
                    }
                )
            chart.set_title({"name": sheet_name.replace(".", " ").title()})
            chart.set_x_axis({"name": x_axis})
            chart.set_y_axis({"name": y_axis})
            worksheet.insert_chart("B3", chart, {"x_scale": 2, "y_scale": 2})

    def save(self):
        """关闭工作簿并将内容保存到目标文件。"""
        self.workbook.close()

    def csv_to_xlsx(self, csv_file, sheet_name, x_axis, y_axis, y_fields=[]):
        """将 CSV 数据写入工作表，并为指定纵轴字段生成趋势图。

        ``csv_file`` 是 CSV 文件路径，``sheet_name`` 是图表名称，
        ``x_axis`` 和 ``y_axis`` 分别是坐标轴名称，``y_fields`` 是需要展示的字段列表。
        """
        filename = os.path.splitext(os.path.basename(csv_file))[0]
        logger.debug("filename:" + filename)
        worksheet_name = self._safe_sheet_name(filename)
        worksheet = self.workbook.add_worksheet(worksheet_name)
        with open(csv_file) as f:
            read = csv.reader(f)
            row = 0
            headings = []
            for line in read:
                r = 0
                for i in line:
                    if self.is_number(i):
                        worksheet.write(row, r, float(i))
                    else:
                        worksheet.write(row, r, i)
                    r = r + 1
                if row == 0:
                    headings = line
                row = row + 1
            columns = len(headings)
        # 根据表头定位需要绘制的字段及系列名称。
        indexs = []
        series_index = []
        for columu_name in y_fields:
            indexs.extend([i for i, v in enumerate(headings) if v == columu_name])
        series_index.extend([i for i, v in enumerate(headings) if v == "package"])
        logger.debug("series_index")
        logger.debug(series_index)
        if columns > 1 and row > 2:
            chart = self.workbook.add_chart({"type": "line"})
            i = 0
            for index in indexs:
                if "pid_cpu%" == headings[index] or "pid_pss(MB)" == headings[index]:
                    chart.add_series(
                        {
                            # 进程指标以包名列作为系列名称。
                            "name": [worksheet_name, 1, series_index[i]],
                            "categories": [worksheet_name, 1, 0, row - 1, 0],
                            "values": [worksheet_name, 1, index, row - 1, index],
                            "line": {"color": self.color_list[index % len(self.color_list)]},
                        }
                    )
                    i = i + 1
                else:
                    chart.add_series(
                        {
                            "name": [worksheet_name, 0, index],
                            "categories": [worksheet_name, 1, 0, row - 1, 0],
                            "values": [worksheet_name, 1, index, row - 1, index],
                            "line": {"color": self.color_list[index % len(self.color_list)]},
                        }
                    )
            chart.set_title({"name": sheet_name})
            chart.set_x_axis({"name": x_axis})
            chart.set_y_axis({"name": y_axis})
            worksheet.insert_chart("L3", chart, {"x_scale": 2, "y_scale": 2})

    def is_number(self, s):
        """判断字符串是否可作为数值写入工作表。"""
        try:
            float(s)
            return True
        except ValueError:
            pass

        try:
            import unicodedata

            unicodedata.numeric(s)
            return True
        except (TypeError, ValueError):
            pass

        return False
