"""mobileperf 解析器对空/畸形输入的健壮性契约测试（对应 B1/B2/B4 修复）。"""

from mobileperf.android.cpu_top import PckCpuinfo
from mobileperf.android.trafficstats import NetDevInfo, TrafficSnapshot


def test_traffic_snapshot_matches_uid_exactly_not_substring():
    source = (
        "2 wlan0 0x0 10123 0 100 10 200 20 0 0 0 0 0 0 0 0 0 0 0 0\n"
        "3 wlan0 0x0 101234 0 999 90 999 90 0 0 0 0 0 0 0 0 0 0 0 0\n"
        "4 rmnet0 0x0 10123 1 300 30 400 40 0 0 0 0 0 0 0 0 0 0 0 0\n"
    )
    snap = TrafficSnapshot(source, "com.example", "10123")

    # 仅 uid 完全等于 10123 的两行被统计，101234 行被排除。
    assert snap.rx_uid_bytes == 100 + 300
    assert snap.tx_uid_bytes == 200 + 400
    assert snap.total_uid_bytes == 1000
    # 第一行 cnt_set=0 记后台，第三行 cnt_set=1 记前台。
    assert snap.bg_bytes == 100 + 200
    assert snap.fg_bytes == 300 + 400


def test_traffic_snapshot_skips_short_malformed_lines():
    source = (
        "2 wlan0 0x0 10123 0 100 10 200\n"  # 列数不足 9
        "broken\n"
        "3 rmnet0 0x0 10123 0 50 5 60 6 0 0 0 0 0 0 0 0 0 0 0 0\n"
    )
    snap = TrafficSnapshot(source, "com.example", "10123")

    assert snap.rx_uid_bytes == 50
    assert snap.tx_uid_bytes == 60


def test_netdev_info_mobile_total_uses_mobile_counters():
    source = (
        "wlan0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n"
        "rmnet0: 300 0 0 0 0 0 0 0 400 0 0 0 0 0 0 0\n"
    )
    info = NetDevInfo(source)

    assert info.wifi_total == 100 + 200
    assert info.mobile_total == 300 + 400
    assert info.total == info.wifi_total + info.mobile_total


def test_pck_cpuinfo_short_line_without_cpu_column_does_not_crash():
    # 无 CPU% 表头时 get_cpucol_index 回退为默认 2，目标行不足 3 列导致 CPU 字段为空。
    source = "123 com.example.app\n"
    info = PckCpuinfo(["com.example.app"], source, sdkversion=26)

    assert info.pid == "123"
    assert info.total_pid_cpu == 0


def test_netdev_info_short_wlan0_line_does_not_crash():
    # wlan0 行字段不足 10 时跳过，不再 items[9] IndexError。
    info = NetDevInfo("wlan0: 100 0 0 0\n")

    assert info.wifi_total == 0
    assert info.total == 0


def test_meminfo_package_short_or_non_numeric_total_is_skipped():
    from mobileperf.android.meminfos import MemInfoPackage

    assert MemInfoPackage("TOTAL\n").totalAllocHeap == 0
    assert MemInfoPackage("TOTAL abc\n").totalAllocHeap == 0
