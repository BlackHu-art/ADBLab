---
kind: class
---

# Excel

- 模块：[[mobileperf.android.excel]]
- 全名：mobileperf.android.excel.Excel

> 封装工作簿、工作表名称归一化和趋势图生成

## 方法

- [[mobileperf.android.excel.Excel.__init__]] — （无 docstring）
- [[mobileperf.android.excel.Excel._safe_sheet_name]] — 返回符合 Excel 限制且在当前工作簿内唯一的工作表名称
- [[mobileperf.android.excel.Excel.add_sheet]] — 写入二维数据，并在数据量足够时插入折线图
- [[mobileperf.android.excel.Excel.save]] — 关闭工作簿并将内容保存到目标文件
- [[mobileperf.android.excel.Excel.csv_to_xlsx]] — 将 CSV 数据写入工作表，并为指定纵轴字段生成趋势图
- [[mobileperf.android.excel.Excel.is_number]] — 判断字符串是否可作为数值写入工作表

