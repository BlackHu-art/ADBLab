---
kind: file
---

# gui.panels.device_manager_responsive

> 提供 Devices 面板的响应式复合计划与自收缩控件层

- 路径：gui/panels/device_manager_responsive.py

## 类

- [[gui.panels.device_manager_responsive._DeviceCompositePlan]] — 同时约束连接行、设备主体和动作按钮网格的复合计划
- [[gui.panels.device_manager_responsive._DeviceResponsiveBinding]] — 把动作网格纳入 Devices 三态复合计划的单一协调目标
- [[gui.panels.device_manager_responsive._ShrinkableDeviceBody]] — 只向外层传播当前计划的一行安全高度，内部仍可按计划堆叠
- [[gui.panels.device_manager_responsive._ShrinkableDeviceList]] — 只向布局声明一行的安全高度，剩余空间仍可由伸展因子分配

