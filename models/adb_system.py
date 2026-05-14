"""
ADB System Mixin — permissions, broadcast, activity, process, content provider,
battery simulation, cmd/service toggles, emulator, IME, package info, quick settings.

Compose with ADBModelCore subclass (e.g. ADBAdvanced). All methods are @async_command.
"""

from .adb_model import async_command
from utils.adb_resolver import CF


class ADBSystemMixin:
    """Mixin providing system-level ADB operations."""

    # ── App Permissions ─────────────────────────────────────────────────

    @async_command
    def grant_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "grant", package, permission]
            )
            return {
                "success": True, "device_ip": device_ip,
                "package": package, "permission": permission, "output": result,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def revoke_permission_async(self, device_ip: str, package: str, permission: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "revoke", package, permission]
            )
            return {
                "success": True, "device_ip": device_ip,
                "package": package, "permission": permission, "output": result,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def reset_permissions_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "reset-permissions", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def list_permissions_async(self, device_ip: str, package: str = "") -> dict:
        try:
            if package:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "pm", "dump", package], timeout=15
                )
            else:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "pm", "list", "permissions"], timeout=15
                )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── App Disable/Enable ──────────────────────────────────────────────

    @async_command
    def disable_package_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "disable", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def enable_package_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "enable", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def disable_package_user_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "disable-user", package]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Broadcast Intents ───────────────────────────────────────────────

    @async_command
    def send_broadcast_async(self, device_ip: str, action: str, extras: dict = None) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "am", "broadcast", "-a", action]
            if extras:
                for k, v in (extras or {}).items():
                    if isinstance(v, bool):
                        cmd.extend(["--ez", k, "true" if v else "false"])
                    elif isinstance(v, int):
                        cmd.extend(["--ei", k, str(v)])
                    elif isinstance(v, float):
                        cmd.extend(["--ef", k, str(v)])
                    else:
                        cmd.extend(["--es", k, str(v)])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Activity Start ──────────────────────────────────────────────────

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
        try:
            cmd = ["adb", "-s", device_ip, "shell", "am", "start"]
            if component:
                cmd.extend(["-n", component])
            if action:
                cmd.extend(["-a", action])
            if data_uri:
                cmd.extend(["-d", data_uri])
            if mime_type:
                cmd.extend(["-t", mime_type])
            if flags:
                cmd.extend(["-f", flags])
            if wait:
                cmd.append("-W")
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def open_deep_link_async(self, device_ip: str, uri: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "am", "start", "-d", uri], timeout=15
            )
            return {"success": True, "device_ip": device_ip, "uri": uri, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Process Management ──────────────────────────────────────────────

    @async_command
    def list_processes_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "ps", "-A"], timeout=10
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def top_snapshot_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "top", "-b", "-n", "1"], timeout=10
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def kill_process_async(self, device_ip: str, pid: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "kill", pid])
            return {"success": True, "device_ip": device_ip, "pid": pid, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Content Provider ────────────────────────────────────────────────

    @async_command
    def content_query_async(
        self, device_ip: str, uri: str, projection: str = "", where: str = "", sort: str = ""
    ) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "content", "query", "--uri", uri]
            if projection:
                cmd.extend(["--projection", projection])
            if where:
                cmd.extend(["--where", where])
            if sort:
                cmd.extend(["--sort", sort])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def content_insert_async(self, device_ip: str, uri: str, binds: dict = None) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "content", "insert", "--uri", uri]
            for k, v in (binds or {}).items():
                cmd.extend(["--bind", f"{k}:s:{v}"])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def content_delete_async(self, device_ip: str, uri: str, where: str = "") -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "shell", "content", "delete", "--uri", uri]
            if where:
                cmd.extend(["--where", where])
            result = self._execute_command(cmd, timeout=15)
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Battery Simulation ──────────────────────────────────────────────

    @async_command
    def battery_set_level_async(self, device_ip: str, level: int) -> dict:
        try:
            self._execute_command(
                ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "set", "level", str(level)]
            )
            return {"success": True, "device_ip": device_ip, "level": level}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def battery_set_status_async(self, device_ip: str, status: str) -> dict:
        try:
            self._execute_command(
                ["adb", "-s", device_ip, "shell", "dumpsys", "battery", "set", "status", str(status)]
            )
            return {"success": True, "device_ip": device_ip, "status": status}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def battery_reset_async(self, device_ip: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "shell", "dumpsys", "battery", "reset"])
            return {"success": True, "device_ip": device_ip}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Service Toggles (svc) ───────────────────────────────────────────

    @async_command
    def cmd_wifi_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "wifi", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_data_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "data", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_bluetooth_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "bluetooth", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_nfc_enable_async(self, device_ip: str, enable: bool) -> dict:
        try:
            action = "enable" if enable else "disable"
            self._execute_command(["adb", "-s", device_ip, "shell", "svc", "nfc", action])
            return {"success": True, "device_ip": device_ip, "action": action}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_statusbar_expand_async(self, device_ip: str) -> dict:
        try:
            self._execute_command(
                ["adb", "-s", device_ip, "shell", "cmd", "statusbar", "expand-settings"]
            )
            return {"success": True, "device_ip": device_ip}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_uimode_night_async(self, device_ip: str, enable: bool) -> dict:
        try:
            mode = "yes" if enable else "no"
            self._execute_command(["adb", "-s", device_ip, "shell", "cmd", "uimode", "night", mode])
            return {"success": True, "device_ip": device_ip, "mode": mode}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_dumpsys_service_async(self, device_ip: str, service: str = "") -> dict:
        try:
            if service:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "dumpsys", service], timeout=20
                )
            else:
                result = self._execute_command(
                    ["adb", "-s", device_ip, "shell", "service", "list"], timeout=10
                )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def cmd_launcher_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "cmd", "shortcut", "get-default-launcher"]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Emulator Control ────────────────────────────────────────────────

    @async_command
    def emu_sms_send_async(self, device_ip: str, sender: str, text: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "emu", "sms", "send", sender, text])
            return {"success": True, "device_ip": device_ip, "sender": sender}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def emu_call_async(self, device_ip: str, number: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "emu", "call", number])
            return {"success": True, "device_ip": device_ip, "number": number}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def emu_geo_fix_async(
        self, device_ip: str, longitude: str, latitude: str, altitude: str = ""
    ) -> dict:
        try:
            cmd = ["adb", "-s", device_ip, "emu", "geo", "fix", longitude, latitude]
            if altitude:
                cmd.append(altitude)
            self._execute_command(cmd)
            return {
                "success": True, "device_ip": device_ip,
                "longitude": longitude, "latitude": latitude,
            }
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def emu_rotate_async(self, device_ip: str) -> dict:
        try:
            self._execute_command(["adb", "-s", device_ip, "emu", "rotate"])
            return {"success": True, "device_ip": device_ip}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── IME Management ──────────────────────────────────────────────────

    @async_command
    def ime_list_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "ime", "list", "-s"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def ime_set_async(self, device_ip: str, ime_id: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "ime", "set", ime_id])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── Package Info Extended ───────────────────────────────────────────

    @async_command
    def pm_path_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "pm", "path", package])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pm_dump_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "dump", package], timeout=15
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pm_list_features_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "pm", "list", "features"], timeout=10
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def pm_list_users_async(self, device_ip: str) -> dict:
        try:
            result = self._execute_command(["adb", "-s", device_ip, "shell", "pm", "list", "users"])
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    # ── App Standby / Force Stop ────────────────────────────────────────

    @async_command
    def set_inactive_async(self, device_ip: str, package: str, inactive: bool) -> dict:
        try:
            state = "true" if inactive else "false"
            self._execute_command(
                ["adb", "-s", device_ip, "shell", "am", "set-inactive", package, state]
            )
            return {"success": True, "device_ip": device_ip, "package": package, "inactive": state}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

    @async_command
    def force_stop_async(self, device_ip: str, package: str) -> dict:
        try:
            result = self._execute_command(
                ["adb", "-s", device_ip, "shell", "am", "force-stop", package]
            )
            return {"success": True, "device_ip": device_ip, "output": result}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}

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
        try:
            if action in actions:
                for cmd_str in actions[action]:
                    shell_cmd = cmd_str.split()
                    full_cmd = ["adb", "-s", device_ip, "shell"] + shell_cmd
                    self._execute_command(full_cmd)
                return {"success": True, "device_ip": device_ip, "action": action}
            return {"success": False, "device_ip": device_ip, "error": f"Unknown action: {action}"}
        except Exception as e:
            return {"success": False, "device_ip": device_ip, "error": str(e)}
