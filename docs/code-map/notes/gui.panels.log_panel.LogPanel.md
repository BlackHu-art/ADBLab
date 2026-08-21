---
kind: class
---

# LogPanel

- 模块：[[gui.panels.log_panel]]
- 全名：gui.panels.log_panel.LogPanel

## 方法

- [[gui.panels.log_panel.LogPanel.__init__]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._apply_style]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._on_theme_changed]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._on_log_font_changed]] — 更新日志字体并按新字号重绘（悬挂缩进按字体度量计算）
- [[gui.panels.log_panel.LogPanel._init_ui]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._connect_services]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._append_log]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._append_logs]] — 接收三元组批次；DEBUG 已由 LogService 在源头过滤，此处不再重复
- [[gui.panels.log_panel.LogPanel._flush_pending_rows]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._render_rows]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._render_entries]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._rerender_all]] — 批量重绘，并恢复用户在历史记录中的滚动锚点
- [[gui.panels.log_panel.LogPanel._row_html]] — 组装单条日志的块级 HTML；时间戳不渲染，悬挂缩进按当前字体度量
- [[gui.panels.log_panel.LogPanel._message_body_html]] — 返回级别标签与消息正文的 HTML；命中缓存时跳过转义与拼接
- [[gui.panels.log_panel.LogPanel._trim_excess]] — 超过上限时按块从文档头部删除，避免整份重绘（O(裁剪行)）
- [[gui.panels.log_panel.LogPanel._remove_head_blocks]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel.dropped_pending_count]] — 返回因界面渲染背压而丢弃的累计日志数
- [[gui.panels.log_panel.LogPanel._pending_capacity]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._bound_pending_backlog]] — 只保留界面最终可能展示的最新日志，防止队列无限增长
- [[gui.panels.log_panel.LogPanel._pending_drop_notice_row]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel._consume_pending_without_render]] — 主题重绘前接纳等待行，避免取消定时器时丢失用户日志
- [[gui.panels.log_panel.LogPanel._cancel_pending_render]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel.closeEvent]] — 关闭时停止防抖定时器并断开类级信号，避免晚到事件触碰已销毁面板
- [[gui.panels.log_panel.LogPanel.clear]] — （无 docstring）
- [[gui.panels.log_panel.LogPanel.set_max_lines]] — 立即应用日志保留上限，并裁剪已经显示的历史记录

