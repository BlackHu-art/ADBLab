from __future__ import annotations

import os
from datetime import datetime

from controllers._base import _ADBControllerBase
from gui.panels.adb_control_signals import ADBControllerSignals
from models.adb_advanced import ADBAdvanced


class ADBFileMixin(_ADBControllerBase):
    """File push/pull/list, port forward/reverse, content query, quick settings, PM features."""

    # ── Provided by _ADBControllerBase ──
    advanced_model: ADBAdvanced
    signals: ADBControllerSignals

    _handlers = {
        "shell_ls": "_process_shell_ls_result",
        "push_file": "_process_push_file_result",
        "pull_file": "_process_pull_file_result",
        "forward_port": "_process_forward_port_result",
        "list_forwards": "_process_list_forwards_result",
        "remove_all_forwards": "_process_remove_all_forwards_result",
        "reverse_port": "_process_reverse_port_result",
        "list_reverse": "_process_list_reverse_result",
        "remove_all_reverse": "_process_remove_all_reverse_result",
        "content_query": "_process_content_query_result",
        "quick_setting": "_process_quick_setting_result",
        "pm_list_features": "_process_pm_list_features_result",
    }

    # -- File Management --

    def file_list(self, devices: list, path: str = "/sdcard"):
        if not devices:
            self._emit_operation("file_list", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.shell_ls_async(ip, path)

    def _process_shell_ls_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "file_list",
                True,
                f"📁 {result.get('path', '')} ({ip}):\n{result.get('output', '')[:2000]}",
            )
        else:
            self._emit_operation(
                "file_list", False, f"File list failed on {ip}: {result.get('error')}"
            )

    def file_push(self, devices: list, local_path: str, remote_path: str):
        if not devices:
            self._emit_operation("file_push", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.push_file_async(ip, local_path, remote_path)

    def _process_push_file_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "file_push", True, f"File pushed to {ip}: {result.get('output', '')}"
            )
        else:
            self._emit_operation("file_push", False, f"Push failed on {ip}: {result.get('error')}")

    def file_pull(self, devices: list, remote_path: str):
        if not devices:
            self._emit_operation("file_pull", False, "⚠️ No devices selected")
            return
        save_dir = self._get_screenshot_dir()
        for ip in devices:
            filename = (
                os.path.basename(remote_path) or f"pulled_{datetime.now().strftime('%H%M%S')}"
            )
            local_path = os.path.join(save_dir, filename)
            self.advanced_model.pull_file_async(ip, remote_path, local_path)

    def _process_pull_file_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "file_pull", True, f"File pulled from {ip}: {result.get('output', '')}"
            )
        else:
            self._emit_operation("file_pull", False, f"Pull failed on {ip}: {result.get('error')}")

    # -- Port Forwarding --

    def forward_port(self, devices: list, local_port: str, remote_port: str):
        if not devices:
            self._emit_operation("forward_port", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.forward_port_async(ip, local_port, remote_port)

    def _process_forward_port_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "forward_port",
                True,
                f"Forwarded {result.get('local')} → {result.get('remote')} on {ip}",
            )
        else:
            self._emit_operation(
                "forward_port", False, f"Forward failed on {ip}: {result.get('error')}"
            )

    def list_forwards(self, devices: list):
        if not devices:
            self._emit_operation("list_forwards", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.list_forwards_async(ip)

    def _process_list_forwards_result(self, result: dict):
        ip = result.get("device_ip", "")
        output = result.get("output", "")
        if result.get("success"):
            self._emit_operation(
                "list_forwards",
                True,
                f"Forward rules ({ip}):\n{output}" if output else f"No forward rules on {ip}",
            )
        else:
            self._emit_operation(
                "list_forwards", False, f"List forwards failed on {ip}: {result.get('error')}"
            )

    def remove_forwards(self, devices: list):
        if not devices:
            self._emit_operation("remove_forwards", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.remove_all_forwards_async(ip)

    def _process_remove_all_forwards_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("remove_forwards", True, f"All forward rules removed on {ip}")
        else:
            self._emit_operation(
                "remove_forwards", False, f"Remove forwards failed on {ip}: {result.get('error')}"
            )

    def reverse_port(self, devices: list, remote_port: str, local_port: str):
        if not devices:
            self._emit_operation("reverse_port", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.reverse_port_async(ip, remote_port, local_port)

    def _process_reverse_port_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("reverse_port", True, f"Reverse forwarded on {ip}")
        else:
            self._emit_operation(
                "reverse_port", False, f"Reverse forward failed on {ip}: {result.get('error')}"
            )

    def list_reverse(self, devices: list):
        if not devices:
            self._emit_operation("list_reverse", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.list_reverse_async(ip)

    def _process_list_reverse_result(self, result: dict):
        ip = result.get("device_ip", "")
        output = result.get("output", "")
        if result.get("success"):
            self._emit_operation(
                "list_reverse",
                True,
                f"Reverse rules ({ip}):\n{output}" if output else f"No reverse rules on {ip}",
            )
        else:
            self._emit_operation(
                "list_reverse", False, f"List reverse failed on {ip}: {result.get('error')}"
            )

    def remove_reverse(self, devices: list):
        if not devices:
            self._emit_operation("remove_reverse", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.remove_all_reverse_async(ip)

    def _process_remove_all_reverse_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation("remove_reverse", True, f"All reverse rules removed on {ip}")
        else:
            self._emit_operation(
                "remove_reverse", False, f"Remove reverse failed on {ip}: {result.get('error')}"
            )

    # ── Content Provider ──

    def content_query(self, devices: list, uri: str):
        if not devices:
            self._emit_operation("content_query", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.content_query_async(ip, uri)

    def _process_content_query_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "content_query", True, f"Content query ({ip}):\n{result.get('output', '')[:2000]}"
            )
        else:
            self._emit_operation(
                "content_query", False, f"Content query failed on {ip}: {result.get('error')}"
            )

    # -- Quick Settings --

    def quick_setting(self, devices: list, action: str):
        if not devices:
            self._emit_operation("quick_setting", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.quick_setting_async(ip, action)

    def _process_quick_setting_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "quick_setting", True, f"Quick setting '{result.get('action')}' applied on {ip}"
            )
        else:
            self._emit_operation(
                "quick_setting", False, f"Quick setting failed on {ip}: {result.get('error')}"
            )

    # ── PM Features ──

    def pm_features(self, devices: list):
        if not devices:
            self._emit_operation("pm_features", False, "⚠️ No devices selected")
            return
        for ip in devices:
            self.advanced_model.pm_list_features_async(ip)

    def _process_pm_list_features_result(self, result: dict):
        ip = result.get("device_ip", "")
        if result.get("success"):
            self._emit_operation(
                "pm_features", True, f"Features ({ip}):\n{result.get('output', '')[:2000]}"
            )
        else:
            self._emit_operation(
                "pm_features", False, f"Features list failed on {ip}: {result.get('error')}"
            )
