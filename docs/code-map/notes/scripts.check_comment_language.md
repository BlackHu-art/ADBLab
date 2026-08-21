---
kind: file
---

# scripts.check_comment_language

> 检查受控 Python 代码中的注释和文档字符串语言

- 路径：scripts/check_comment_language.py

## 类

- [[scripts.check_comment_language.LanguageIssue]] — 描述一处不符合中文注释规范的问题

## 函数

- [[scripts.check_comment_language._build_parser]] — （无 docstring）
- [[scripts.check_comment_language._contains_mojibake]] — 判断文本是否包含明确的替换符或常见 UTF-8 误解码片段
- [[scripts.check_comment_language._docstring_nodes]] — 遍历模块、类和函数节点中的真实文档字符串
- [[scripts.check_comment_language._is_exempt]] — 判断文本是否属于无需翻译的机器指令、许可证或技术标识
- [[scripts.check_comment_language._iter_python_files]] — 按明确的受控范围枚举 Python 文件，并跳过第三方和生成目录
- [[scripts.check_comment_language._requires_chinese]] — 判断自然语言说明是否缺少中文内容
- [[scripts.check_comment_language.main]] — 运行检查并以非零状态报告不合规内容
- [[scripts.check_comment_language.scan_file]] — 检查单个 Python 文件，不把普通字符串误判为注释
- [[scripts.check_comment_language.scan_paths]] — 检查受控路径并返回稳定排序的问题列表

