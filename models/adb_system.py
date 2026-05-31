"""
ADB System Mixin — permissions, broadcast, activity, process, content provider,
battery simulation, cmd/service toggles, emulator, IME, package info, quick settings.

Compose with ADBModelCore subclass (e.g. ADBAdvanced). All methods are @async_command.
"""

from .adb_model import async_command


class ADBSystemMixin:
    """Mixin providing system-level ADB operations."""

    # ── App Permissions ─────────────────────────────────────────────────

    @async_command
    def grant_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "grant", package, permission],
            device_ip=device_ip, package=package, permission=permission,
        )

    @async_command
    def revoke_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "revoke", package, permission],
            device_ip=device_ip, package=package, permission=permission,
        )

    @async_command
    def reset_permissions_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "reset-permissions", package],
            device_ip=device_ip, package=package,
        )

    @async_command
    def list_permissions_async(self, device_ip: str, package: str = "") -> dict:
        if package:
            cmd = ["adb", "-s", device_ip, "shell", "pm", "dump", package]
        else:
            cmd = ["adb", "-s", device_ip, "shell", "pm", "list", "permissions"]
        return self._run(cmd, timeout=15, device_ip=device_ip, package=package)

    # ── App Disable/Enable ──────────────────────────────────────────────

    @async_command
    def disable_package_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "disable", package],
            device_ip=device_ip, package=package,
        )

    @async_command
    def enable_package_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "enable", package],
            device_ip=device_ip, package=package,
        )

    @async_command
    def disable_package_user_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "disable-user", package],
            device_ip=device_ip, package=package,
        )

    # ── Broadcast Intents ───────────────────────────────────────────────

    @async_command
    def send_broadcast_async(self, device_ip: str, action: str, extras: dict = None) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "am", "broadcast", "-a", action]
        if extras:
            for k, v in extras.items():
                if isinstance(v, bool):
                    cmd.extend(["--ez", k, "true" if v else "false"])
                elif isinstance(v, int):
                    cmd.extend(["--ei", k, str(v)])
                elif isinstance(v, float):
                    cmd.extend(["--ef", k, str(v)])
                else:
                    cmd.extend(["--es", k, str(v)])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    # ── Activity Start ──────────────────────────────────────────────────

    @async_command
    def start_activity_async(self, device_ip: str, component: str = "",
                             action: str = "", data_uri: str = "",
                             mime_type: str = "", flags: str = "",
                             wait: bool = False) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "am", "start"]
        if component:   cmd.extend(["-n", component])
        if action:      cmd.extend(["-a", action])
        if data_uri:    cmd.extend(["-d", data_uri])
        if mime_type:   cmd.extend(["-t", mime_type])
        if flags:       cmd.extend(["-f", flags])
        if wait:        cmd.append("-W")
        return self._run(cmd, timeout=15, device_ip=device_ip)

    @async_command
    def open_deep_link_async(self, device_ip: str, uri: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "am", "start", "-d", uri],
            timeout=15, device_ip=device_ip, uri=uri,
        )

    # ── Process Management ──────────────────────────────────────────────

    @async_command
    def list_processes_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ps", "-A"],
            timeout=10, device_ip=device_ip,
        )

    @async_command
    def top_snapshot_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "top", "-b", "-n", "1"],
            timeout=10, device_ip=device_ip,
        )

    @async_command
    def kill_process_async(self, device_ip: str, pid: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "kill", pid],
            device_ip=device_ip, pid=pid,
        )

    # ── Content Provider ────────────────────────────────────────────────

    @async_command
    def content_query_async(self, device_ip: str, uri: str,
                            projection: str = "", where: str = "",
                            sort: str = "") -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "content", "query", "--uri", uri]
        if projection:  cmd.extend(["--projection", projection])
        if where:       cmd.extend(["--where", where])
        if sort:        cmd.extend(["--sort", sort])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    @async_command
    def content_insert_async(self, device_ip: str, uri: str, binds: dict = None) -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "content", "insert", "--uri", uri]
        for k, v in (binds or {}).items():
            cmd.extend(["--bind", f"{k}:s:{v}"])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    @async_command
    def content_delete_async(self, device_ip: str, uri: str, where: str = "") -> dict:
        cmd = ["adb", "-s", device_ip, "shell", "content", "delete", "--uri", uri]
        if where:
            cmd.extend(["--where", where])
        return self._run(cmd, timeout=15, device_ip=device_ip)

    # ── Battery Simulation ──────────────────────────────────────────────

    @async_command
    def battery_set_level_async(self, device_ip: str, level: int) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "set", "level", str(level)],
            device_ip=device_ip, level=level,
        )

    @async_command
    def battery_set_status_async(self, device_ip: str, status: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "set", "status", str(status)],
            device_ip=device_ip, status=status,
        )

    @async_command
    def battery_reset_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "reset"],
            device_ip=device_ip,
        )

    # ── Service Toggles (svc) ───────────────────────────────────────────

    @async_command
    def cmd_wifi_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "wifi", action],
            device_ip=device_ip, action=action,
        )

    @async_command
    def cmd_data_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "data", action],
            device_ip=device_ip, action=action,
        )

    @async_command
    def cmd_bluetooth_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "bluetooth", action],
            device_ip=device_ip, action=action,
        )

    @async_command
    def cmd_nfc_enable_async(self, device_ip: str, enable: bool) -> dict:
        action = "enable" if enable else "disable"
        return self._run(
            ["adb", "-s", device_ip, "shell", "svc", "nfc", action],
            device_ip=device_ip, action=action,
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
            device_ip=device_ip, mode=mode,
        )

    @async_command
    def cmd_dumpsys_service_async(self, device_ip: str, service: str = "") -> dict:
        if service:
            cmd = ["adb", "-s", device_ip, "shell", "dumpsys", service]
            timeout = 20
        else:
            cmd = ["adb", "-s", device_ip, "shell", "service", "list"]
            timeout = 10
        return self._run(cmd, timeout=timeout, device_ip=device_ip)

    @async_command
    def cmd_launcher_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "cmd", "shortcut", "get-default-launcher"],
            device_ip=device_ip,
        )

    # ── Emulator Control ────────────────────────────────────────────────

    @async_command
    def emu_sms_send_async(self, device_ip: str, sender: str, text: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "emu", "sms", "send", sender, text],
            device_ip=device_ip, sender=sender,
        )

    @async_command
    def emu_call_async(self, device_ip: str, number: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "emu", "call", number],
            device_ip=device_ip, number=number,
        )

    @async_command
    def emu_geo_fix_async(self, device_ip: str, longitude: str,
                          latitude: str, altitude: str = "") -> dict:
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

    # ── IME Management ──────────────────────────────────────────────────

    @async_command
    def ime_list_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ime", "list", "-s"],
            device_ip=device_ip,
        )

    @async_command
    def ime_set_async(self, device_ip: str, ime_id: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "ime", "set", ime_id],
            device_ip=device_ip,
        )

    # ── Package Info Extended ───────────────────────────────────────────

    @async_command
    def pm_path_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "path", package],
            device_ip=device_ip,
        )

    @async_command
    def pm_dump_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "dump", package],
            timeout=15, device_ip=device_ip,
        )

    @async_command
    def pm_list_features_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "list", "features"],
            timeout=10, device_ip=device_ip,
        )

    @async_command
    def pm_list_users_async(self, device_ip: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "pm", "list", "users"],
            device_ip=device_ip,
        )

    # ── App Standby / Force Stop ────────────────────────────────────────

    @async_command
    def set_inactive_async(self, device_ip: str, package: str, inactive: bool) -> dict:
        state = "true" if inactive else "false"
        return self._run(
            ["adb", "-s", device_ip, "shell", "am", "set-inactive", package, state],
            device_ip=device_ip, package=package, inactive=state,
        )

    @async_command
    def force_stop_async(self, device_ip: str, package: str) -> dict:
        return self._run(
            ["adb", "-s", device_ip, "shell", "am", "force-stop", package],
            device_ip=device_ip,
        )

    # ── Quick Settings ──────────────────────────────────────────────────

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
