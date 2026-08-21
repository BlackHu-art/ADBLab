---
kind: class
---

# ADB

- 模块：[[mobileperf.android.tools.androiddevice]]
- 全名：mobileperf.android.tools.androiddevice.ADB

> 本地ADB

## 方法

- [[mobileperf.android.tools.androiddevice.ADB.__init__]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.DEVICEID]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.get_adb_path]] — 返回adb.exe的绝对路径。优先使用指定的adb，若环境变量未指定，则返回当前脚本tools目录下的adb
- [[mobileperf.android.tools.androiddevice.ADB.get_os_name]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.is_connected]] — 检查设备是否连接上
- [[mobileperf.android.tools.androiddevice.ADB.list_device]] — 获取设备列表
- [[mobileperf.android.tools.androiddevice.ADB.recover]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.checkAdbNormal]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.kill_server]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.start_server]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.killOccupy5037Process]] — 终止占用 5037 端口的进程（ADB server 端口冲突处理）
- [[mobileperf.android.tools.androiddevice.ADB._timer]] — 进程超时器，监控adb同步命令执行是否超时，超时强制结束执行。当timeout<=0时，永不超时
- [[mobileperf.android.tools.androiddevice.ADB._run_cmd_once]] — 执行一次adb命令：cmd
- [[mobileperf.android.tools.androiddevice.ADB.run_adb_cmd]] — 尝试执行adb命令
- [[mobileperf.android.tools.androiddevice.ADB.run_shell_cmd]] — 执行 adb shell 命令
- [[mobileperf.android.tools.androiddevice.ADB._check_need_quote]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB._logcat_thread_func]] — 获取logcat线程
- [[mobileperf.android.tools.androiddevice.ADB.save]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.start_logcat]] — 运行logcat进程
- [[mobileperf.android.tools.androiddevice.ADB.stop_logcat]] — 停止logcat进程
- [[mobileperf.android.tools.androiddevice.ADB.wait_for_device]] — 等待设备连接
- [[mobileperf.android.tools.androiddevice.ADB.bugreport]] — adb bugreport ~/Downloads/bugreport.zip
- [[mobileperf.android.tools.androiddevice.ADB.push_file]] — 拷贝文件到手机中
- [[mobileperf.android.tools.androiddevice.ADB.pull_file]] — 从手机中拉取文件
- [[mobileperf.android.tools.androiddevice.ADB.pull_file_between_time]] — 提取/data/anr 目录下 在起止时间戳之间的文件
- [[mobileperf.android.tools.androiddevice.ADB.screencap_out]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.screencap]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.delete_file]] — 删除手机上文件
- [[mobileperf.android.tools.androiddevice.ADB.delete_folder]] — 删除手机上的目录
- [[mobileperf.android.tools.androiddevice.ADB.check_path_size]] — 检测手机上目录空间占比，超过多少比例
- [[mobileperf.android.tools.androiddevice.ADB.is_exist]] — 判断文件或文件夹是否存在
- [[mobileperf.android.tools.androiddevice.ADB.mkdir]] — 在设备上创建目录
- [[mobileperf.android.tools.androiddevice.ADB.list_dir]] — 列取目录下文件 文件夹
- [[mobileperf.android.tools.androiddevice.ADB.list_dir_between_time]] — 列取目录下 起止时间点之间的文件
- [[mobileperf.android.tools.androiddevice.ADB.is_overtime_days]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.start_activity]] — 打开一个Activity
- [[mobileperf.android.tools.androiddevice.ADB.get_focus_activity]] — 通过dumpsys window windows获取activity名称  window名?
- [[mobileperf.android.tools.androiddevice.ADB.get_foreground_process]] — :return: 当前前台进程名,对get_focus_activity的返回结果加以处理
- [[mobileperf.android.tools.androiddevice.ADB.get_current_activity]] — 获取当前activity名
- [[mobileperf.android.tools.androiddevice.ADB.get_top_activity_with_activity_top]] — 通过dumpsys activity top 获取当前activity名
- [[mobileperf.android.tools.androiddevice.ADB.get_top_activity_with_usagestats]] — 通过dumpsys usagestats获取当前activity名
- [[mobileperf.android.tools.androiddevice.ADB.get_pid_from_pck]] — 从ps信息中通过匹配包名，获取进程pid号，对于双开应用统计值会返回两个不同的pid后面再优化
- [[mobileperf.android.tools.androiddevice.ADB.get_pckinfo_from_ps]] — 从ps中获取应用的信息:pid,uid,packagename
- [[mobileperf.android.tools.androiddevice.ADB.get_process_stack]] — :param package_name: 进程名
- [[mobileperf.android.tools.androiddevice.ADB.get_process_stack_from_pid]] — :param package_name: 进程名
- [[mobileperf.android.tools.androiddevice.ADB.dumpheap]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.dump_native_heap]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.clear_data]] — 清除指定包的 用户数据
- [[mobileperf.android.tools.androiddevice.ADB.stop_package]] — 杀死指定包的进程
- [[mobileperf.android.tools.androiddevice.ADB.input]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.ping]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.get_system_version]] — 获取系统版本，如：4.1.2
- [[mobileperf.android.tools.androiddevice.ADB.get_genie_uuid]] — 获取设备 UUID
- [[mobileperf.android.tools.androiddevice.ADB.get_genie_wifi]] — 获取设备 Wi-Fi MAC 地址
- [[mobileperf.android.tools.androiddevice.ADB.get_package_ver]] — 获取应用版本信息
- [[mobileperf.android.tools.androiddevice.ADB.get_sdk_version]] — 获取SDK版本，如：16
- [[mobileperf.android.tools.androiddevice.ADB.get_phone_brand]] — 获取手机品牌  如：Mi Samsung OnePlus
- [[mobileperf.android.tools.androiddevice.ADB.get_phone_model]] — 获取手机型号  如：A0001 M2S
- [[mobileperf.android.tools.androiddevice.ADB.get_screen_size]] — 获取屏幕大小  如：5.5 可能获取不到
- [[mobileperf.android.tools.androiddevice.ADB.get_wm_size]] — 获取屏幕分辨率  如：Physical size:1080*1920
- [[mobileperf.android.tools.androiddevice.ADB.get_cpu_abi]] — 获取系统的CPU架构信息
- [[mobileperf.android.tools.androiddevice.ADB.find_tag_index]] — 查找指定的 tag 在一行中以空白分隔的下标
- [[mobileperf.android.tools.androiddevice.ADB.get_device_imei]] — 获取手机串号
- [[mobileperf.android.tools.androiddevice.ADB.get_process_pids]] — 查找包含指定进程名的进程PID
- [[mobileperf.android.tools.androiddevice.ADB.is_process_running]] — 判断进程是否存活
- [[mobileperf.android.tools.androiddevice.ADB.get_uid]] — 获取APP的uid
- [[mobileperf.android.tools.androiddevice.ADB.getUID]] — 获取app的uid
- [[mobileperf.android.tools.androiddevice.ADB.is_app_installed]] — 判断app是否安装
- [[mobileperf.android.tools.androiddevice.ADB.list_installed_app]] — 获取已安装app列表
- [[mobileperf.android.tools.androiddevice.ADB.list_process]] — 获取进程列表
- [[mobileperf.android.tools.androiddevice.ADB.kill_process]] — 杀死包含指定进程
- [[mobileperf.android.tools.androiddevice.ADB.wait_proc_exit]] — 等待指定进程退出
- [[mobileperf.android.tools.androiddevice.ADB.forward]] — 端口转发
- [[mobileperf.android.tools.androiddevice.ADB.reboot]] — 重启手机
- [[mobileperf.android.tools.androiddevice.ADB._copy_set_propex]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.set_secure_property]] — 通过setpropex设置手机安全属性(发布版手机默认安全属性无法打开ViewServer)
- [[mobileperf.android.tools.androiddevice.ADB._install_apk]] — （无 docstring）
- [[mobileperf.android.tools.androiddevice.ADB.install_apk]] — 安装应用
- [[mobileperf.android.tools.androiddevice.ADB.uninstall_apk]] — 卸载应用

