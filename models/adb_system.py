"""提供权限、广播、Activity、进程、电池模拟和输入法等 ADB 系统操作。

该 mixin 应与 ADBModelCore 子类组合使用，公开操作均通过 @async_command 异步执行。
"""

import shlex
from typing import Any

from utils.adb_values import normalize_android_package, normalize_dumpsys_service

from .adb_model import async_command


class ADBSystemMixin:
    """系统级 ADB 操作 mixin；与 ADBModelCore 组合后提供 _run 执行入口。"""

    _run: Any

    # 应用权限

    @async_command
    def grant_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        return self._run(
            [
                "adb", "-s", device_ip, "shell", "pm", "grant",
                shlex.quote(package), shlex.quote(permission),
            ],
            device_ip=device_ip,
            package=package,
            permission=permission,
        )

    @async_command
    def revoke_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        return self._run(
            [
                "adb", "-s", device_ip, "shell", "pm", "revoke",
                shlex.quote(package), shlex.quote(permission),
            ],
            device_ip=device_ip,
            package=package,
            permission=permission,
        )

    @async_command
    def reset_permissions_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "reset-permissions", shlex.quote(package)],
            device_ip=device_ip,
            package=package,
        )

    @async_command
    def list_permissions_async(self, device_ip: str, package: str = "") -> dict:
        if package:
            cmd = ["adb", "-s", device_ip, "shell", "pm", "dump", shlex.quote(package)]
        else:
            cmd = ["adb", "-s", device_ip, "shell", "pm", "list", "permissions"]
        return self._run(cmd, timeout=15, device_ip=device_ip, package=package)

    # 应用启用与停用

    @async_command
    def disable_package_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "disable", shlex.quote(package)],
            device_ip=device_ip,
            package=package,
        )

    @async_command
    def enable_package_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "enable", shlex.quote(package)],
            device_ip=device_ip,
            package=package,
        )

    @async_command
    def disable_package_user_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "disable-user", shlex.quote(package)],
            device_ip=device_ip,
            package=package,
        )

    # 广播 Intent

    @async_command
    def send_broadcast_async(self, device_ip: str, action: str, extras: dict | None = None) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "am", "broadcast", "-a", shlex.quote(action)]
        if extras:
            for k, v in extras.items():
                if isinstance(v, bool):
                    cmd.extend(["--ez", shlex.quote(str(k)), "true" if v else "false"])
                elif isinstance(v, int):
                    cmd.extend(["--ei", shlex.quote(str(k)), str(v)])
                elif isinstance(v, float):
                    cmd.extend(["--ef", shlex.quote(str(k)), str(v)])
                else:
                    cmd.extend(["--es", shlex.quote(str(k)), shlex.quote(str(v))])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    # Activity 启动

    @async_command
    def start_activity_async(
        self,
        device_ip: str,
        component: str = "",
        action: str = "",
        data_uri: str = "",
        mime_type: str = "",
        flags: str = "",
        wait: bool = False,
    ) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "am", "start"]
        if component:
            cmd.extend(["-n", shlex.quote(component)])
        if action:
            cmd.extend(["-a", shlex.quote(action)])
        if data_uri:
            cmd.extend(["-d", shlex.quote(data_uri)])
        if mime_type:
            cmd.extend(["-t", shlex.quote(mime_type)])
        if flags:
            cmd.extend(["-f", shlex.quote(flags)])
        if wait:
            cmd.append("-W")
        return self._run(cmd, timeout=15, device_ip=device_ip)

    @async_command
    def open_deep_link_async(self, device_ip: str, uri: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "am", "start", "-d", shlex.quote(uri)],
            timeout=15,
            device_ip=device_ip,
            uri=uri,
        )

    # 进程管理

    @async_command
    def list_processes_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ps", "-A"],
            timeout=10,
            device_ip=device_ip,
        )

    @async_command
    def top_snapshot_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "top", "-b", "-n", "1"],
            timeout=10,
            device_ip=device_ip,
        )

    @async_command
    def gfxinfo_async(self, device_ip: str, package: str) -> dict:
        package = normalize_android_package(package)
        return self._run(
            [
                "adb",
                "-s",
                device_ip,
                "shell",
                "dumpsys",
                "gfxinfo",
                package,
                "framestats",
            ],
            timeout=15,
            device_ip=device_ip,
            package=package,
        )

    @async_command
    def wakelocks_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "cat", "/proc/wakelocks"],
            timeout=10,
            device_ip=device_ip,
        )

    @async_command
    def netstats_detail_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "netstats", "detail"],
            timeout=20,
            device_ip=device_ip,
        )

    @async_command
    def kill_process_async(self, device_ip: str, pid: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "kill", shlex.quote(str(pid))],
            device_ip=device_ip,
            pid=pid,
        )

    # 内容提供器（Content Provider）

    @async_command
    def content_query_async(
        self, device_ip: str, uri: str, projection: str = "", where: str = "", sort: str = ""
    ) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "content", "query", "--uri", shlex.quote(uri)]
        if projection:
            cmd.extend(["--projection", shlex.quote(projection)])
        if where:
            cmd.extend(["--where", shlex.quote(where)])
        if sort:
            cmd.extend(["--sort", shlex.quote(sort)])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    @async_command
    def content_insert_async(self, device_ip: str, uri: str, binds: dict | None = None) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "content", "insert", "--uri", shlex.quote(uri)]
        for k, v in (binds or {}).items():
            key, value = str(k), str(v)
            # bind 语法为 key:type:value，冒号或空值会破坏解析并污染命令结构。
            if not key or not value or ":" in key or ":" in value:
                raise ValueError(f"invalid content insert bind: {k!r}={v!r}")
            cmd.extend(["--bind", f"{key}:s:{value}"])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    @async_command
    def content_delete_async(self, device_ip: str, uri: str, where: str = "") -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "content", "delete", "--uri", shlex.quote(uri)]
        if where:
            cmd.extend(["--where", shlex.quote(where)])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    # 电池状态模拟

    @async_command
    def battery_set_level_async(self, device_ip: str, level: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "set", "level", str(level)],
            device_ip=device_ip,
            level=level,
        )

    @async_command
    def battery_set_status_async(self, device_ip: str, status: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "set", "status", str(status)],
            device_ip=device_ip,
            status=status,
        )

    @async_command
    def battery_reset_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "reset"],
            device_ip=device_ip,
        )

    # svc 系统服务开关

    @async_command
    def cmd_wifi_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "wifi", action],
            device_ip=device_ip,
            action=action,
        )

    @async_command
    def cmd_data_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "data", action],
            device_ip=device_ip,
            action=action,
        )

    @async_command
    def cmd_bluetooth_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "bluetooth", action],
            device_ip=device_ip,
            action=action,
        )

    @async_command
    def cmd_nfc_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "nfc", action],
            device_ip=device_ip,
            action=action,
        )

    @async_command
    def cmd_statusbar_expand_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "cmd", "statusbar", "expand-settings"],
            device_ip=device_ip,
        )

    @async_command
    def cmd_uimode_night_async(self, device_ip: str, enable: bool) -> dict:
        mode = "yes" if enable else "no"
        return self._run(
            ["adb", "-s", device_ip, "shell", "cmd", "uimode", "night", mode],
            device_ip=device_ip,
            mode=mode,
        )

    @async_command
    def cmd_dumpsys_service_async(self, device_ip: str, service: str = "") -> dict:
        service = normalize_dumpsys_service(service)
        if service:
            cmd = ["adb", "-s", device_ip, "shell", "dumpsys", service]
            timeout = 20
        else:
            cmd = ["adb", "-s", device_ip, "shell", "service", "list"]
            timeout = 10
        return self._run(cmd, timeout=timeout, device_ip=device_ip, service=service)

    @async_command
    def cmd_launcher_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "cmd", "shortcut", "get-default-launcher"],
            device_ip=device_ip,
        )

    # 模拟器控制

    @async_command
    def emu_sms_send_async(self, device_ip: str, sender: str, text: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "emu", "sms", "send", sender, text],
            device_ip=device_ip,
            sender=sender,
        )

    @async_command
    def emu_call_async(self, device_ip: str, number: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "emu", "call", number],
            device_ip=device_ip,
            number=number,
        )

    @async_command
    def emu_geo_fix_async(
        self, device_ip: str, longitude: str, latitude: str, altitude: str = ""
    ) -> dict:
        cmd = ["adb", "-s", device_ip, "emu", "geo", "fix", longitude, latitude]
        if altitude:
            cmd.append(altitude)
        return self._run(cmd, device_ip=device_ip, longitude=longitude, latitude=latitude)

    @async_command
    def emu_rotate_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "emu", "rotate"],
            device_ip=device_ip,
        )

    # 输入法管理

    @async_command
    def ime_list_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ime", "list", "-s"],
            device_ip=device_ip,
        )

    @async_command
    def ime_set_async(self, device_ip: str, ime_id: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ime", "set", shlex.quote(ime_id)],
            device_ip=device_ip,
        )

    # 扩展包信息

    @async_command
    def pm_path_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "path", shlex.quote(package)],
            device_ip=device_ip,
        )

    @async_command
    def pm_dump_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "dump", shlex.quote(package)],
            timeout=15,
            device_ip=device_ip,
        )

    @async_command
    def pm_list_features_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "list", "features"],
            timeout=10,
            device_ip=device_ip,
        )

    @async_command
    def pm_list_users_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "list", "users"],
            device_ip=device_ip,
        )

    # 应用待机与强制停止

    @async_command
    def set_inactive_async(self, device_ip: str, package: str, inactive: bool) -> dict:
        state = "true" if inactive else "false"
        return self._run(
            ["adb", "-s", device_ip, "shell", "am", "set-inactive", shlex.quote(package), state],
            device_ip=device_ip,
            package=package,
            inactive=state,
        )

    @async_command
    def force_stop_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "am", "force-stop", shlex.quote(package)],
            device_ip=device_ip,
        )

    # 快捷设置

    @async_command
    def quick_setting_async(self, device_ip: str, action: str) -> dict:
        actions = {
            "anim_off": [
                "settings put global animator_duration_scale 0",
                "settings put global transition_animation_scale 0",
                "settings put global window_animation_scale 0",
            ],
            "anim_on": [
                "settings put global animator_duration_scale 1",
                "settings put global transition_animation_scale 1",
                "settings put global window_animation_scale 1",
            ],
            "stay_awake": ["settings put global stay_on_while_plugged_in 7"],
        }
        if action not in actions:
            return {"success": False, "device_ip": device_ip, "error": f"Unknown action: {action}"}
        # 多个 settings 写入合成一个 shell，减少动画开关等快捷操作的 ADB 进程往返。
        shell_cmd = " && ".join(actions[action])
        result = self._run(
            ["adb", "-s", device_ip, "shell", shell_cmd],
            device_ip=device_ip,
            action=action,
        )
        if result.get("success"):
            return {"success": True, "device_ip": device_ip, "action": action}
        return result
