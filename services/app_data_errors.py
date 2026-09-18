"""按清数据命令的诊断识别系统权限拒绝，不推测设备设置或触发补救命令。"""

import re

CLEAR_DATA_PERMISSION_DENIED = "clear_data_permission_denied"
CLEAR_DATA_PERMISSION_MESSAGE = (
    "系统拒绝通过 ADB 清除应用数据。请在手机的应用信息页手动清除；"
    "若入口也受限，请联系设备管理员或系统厂商。"
)

_SECURITY_DENIAL = re.compile(
    r"(?:^|\s)(?:java\.lang\.)?SecurityException\s*:|\bPermission Denial\s*:",
    re.IGNORECASE,
)


def clear_data_error_code(output: str = "", error: str = "") -> str:
    """仅分类已经失败的清数据命令；原始诊断由调用方保留。

    同一权限异常也可能来自受保护应用，不能据此断言调试开关未开启或系统厂商缺陷。
    本函数不查询设备，不把连接失败、超时或单独出现的权限名误判为系统权限拒绝。
    """
    diagnostic = f"{output}\n{error}"
    if _SECURITY_DENIAL.search(diagnostic):
        return CLEAR_DATA_PERMISSION_DENIED
    lowered = diagnostic.casefold()
    if "android.permission.clear_app_user_data" in lowered and any(
        marker in lowered for marker in (
            "does not have permission", "permission denied", "requires", "not granted",
        )
    ):
        return CLEAR_DATA_PERMISSION_DENIED
    return ""
