"""应用列表、详情及批量标记的纯值解析；不执行命令或接触 Qt。"""

import re

InstalledApp = tuple[str, str, str, str]
PackageDetail = tuple[str, str, str, str]
AppDetails = dict[str, str]

_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.]+$")


def is_safe_package(package: object) -> bool:
    """校验包名为安全 token，拒绝 shell 元字符与路径分隔符。"""
    return bool(_PACKAGE_NAME_RE.fullmatch(str(package or "")))
_DETAIL_BEGIN = "__ADBLAB_PKG_BEGIN_{}__"
_DETAIL_END = "__ADBLAB_PKG_END_{}__"


def split_package_detail_sections(output: str, count: int) -> dict[int, str]:
    """只接纳首尾标记完整的详情，截断尾段留给有剩余预算的兼容查询。"""
    sections: dict[int, list[str]] = {}
    complete: dict[int, str] = {}
    current: int | None = None
    begin_markers = {_DETAIL_BEGIN.format(i): i for i in range(count)}
    end_markers = {_DETAIL_END.format(i): i for i in range(count)}
    for line in output.splitlines():
        stripped = line.strip()
        if stripped in begin_markers:
            current = begin_markers[stripped]
            sections[current] = []
            continue
        if stripped in end_markers:
            if current is not None and current == end_markers[stripped]:
                complete[current] = "\n".join(sections[current])
                current = None
            continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return complete


def has_package_detail(output: str) -> bool:
    """仅版本字段能区分包详情与返回零退出码的设备诊断。"""
    return re.search(r"\bversionCode=\d+", output) is not None


def parse_installed_apps(package_output: str, disabled_output: str) -> list[InstalledApp]:
    """保留设备原顺序、重复项及路径分类，禁用状态属于同一用户快照。"""
    disabled = {line.replace("package:", "").strip() for line in disabled_output.splitlines()}
    apps = []
    for line in package_output.splitlines():
        parts = line.split("=")
        pkg = parts[-1].strip()
        fp = "=".join(parts[:-1]).replace("package:", "").strip()
        if not pkg:
            continue
        if "/data/app/" in fp:
            atype = "User"
        elif "/system/" in fp:
            atype = "System"
        elif "/vendor/" in fp:
            atype = "Vendor"
        else:
            atype = "Other"
        name = pkg.split(".")[-1].replace("_", " ").capitalize()
        st = "Disabled" if pkg in disabled else "Enabled"
        apps.append((name, pkg, st, atype))
    return apps


def parse_batch_detail(package: str, output: str) -> PackageDetail:
    """批量载荷保留原包尾名称、空版本和安装日期默认值。"""
    m_label = re.search(r"nonLocalizedLabel[=:]\s*(\S.+)", output)
    label = m_label.group(1).strip() if m_label else ""
    m_vn = re.search(r"versionName=([\S]+)", output)
    m_vc = re.search(r"versionCode=(\d+)", output)
    vn = m_vn.group(1) if m_vn else ""
    vc = m_vc.group(1) if m_vc else ""
    m_it = re.search(r"firstInstallTime=(\d{4}-\d{2}-\d{2})", output)
    itime = m_it.group(1) if m_it else ""
    return (package, label or package.split(".")[-1], f"{vn} ({vc})" if vn else "", itime)


def parse_app_details(package: str, output: str) -> AppDetails:
    """独立详情固定六个字段；路径保留设备行尾空白。"""
    m_cp = re.search(r"codePath=(.*)", output)
    m_label = re.search(r"nonLocalizedLabel[=:]\s*(\S.+)", output)
    m_vn = re.search(r"versionName=([\S]+)", output)
    m_vc = re.search(r"versionCode=(\d+)", output)
    m_ms = re.search(r"minSdk=(\d+)", output)
    m_ts = re.search(r"targetSdk=(\d+)", output)
    label = m_label.group(1).strip() if m_label else package.split(".")[-1].capitalize()
    return (
        {
            "App Name": label,
            "Package": package,
            "Path": m_cp.group(1) if m_cp else "?",
            "Version": (
                f"{m_vn.group(1) if m_vn else '?'} (code "
                f"{m_vc.group(1) if m_vc else '?'})"
            ),
            "Min SDK": m_ms.group(1) if m_ms else "?",
            "Target SDK": m_ts.group(1) if m_ts else "?",
        }
    )
