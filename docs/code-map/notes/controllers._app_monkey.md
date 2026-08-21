---
kind: file
---

# controllers._app_monkey

> 提供 Monkey 压测的启动、停止与批次状态协调能力

- 路径：controllers/_app_monkey.py

## 类

- [[controllers._app_monkey.ADBAppMonkeyMixin]] — 协调 Monkey 压测的启动、停止与批次状态

## 函数

- [[controllers._app_monkey._emit_monkey_target_finished]] — 在信号存在时发布带批次标识的 Monkey 设备终态
- [[controllers._app_monkey._finalize_monkey_target]] — 在运行终态和停止确认均满足后，原子释放设备批次
- [[controllers._app_monkey._monkey_state_map]] — 返回 Controller 上指定的 Monkey 批次映射

