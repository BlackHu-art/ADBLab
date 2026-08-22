"""utils.adb_values 白名单/校验函数的契约测试（注入防御层）。"""

from decimal import Decimal

import pytest

from utils.adb_values import (
    DUMPSYS_SERVICES,
    normalize_android_package,
    normalize_dumpsys_service,
    normalize_geo_coordinate,
    normalize_tcp_port,
    truncate_diagnostic_output,
)


class TestNormalizeTcpPort:
    def test_valid_port(self):
        assert normalize_tcp_port("5555") == "5555"
        assert normalize_tcp_port(5555) == "5555"

    @pytest.mark.parametrize(
        "bad", ["0", "65536", "-1", "abc", "55;rm", "55 66", "", "5.5"]
    )
    def test_invalid_port_rejected(self, bad):
        with pytest.raises(ValueError):
            normalize_tcp_port(bad)


class TestNormalizeAndroidPackage:
    def test_valid_package(self):
        assert normalize_android_package("com.example.app") == "com.example.app"

    @pytest.mark.parametrize(
        "bad",
        [
            "com.example;rm",
            "com.example$(id)",
            "com.example |reboot",
            "com.example&reboot",
            "a",
            "",
            "..",
            ".com",
            "com..example",
            "com.example/../../etc",
            "COM EXAMPLE",
        ],
    )
    def test_invalid_package_rejected(self, bad):
        with pytest.raises(ValueError):
            normalize_android_package(bad)


class TestNormalizeDumpsysService:
    def test_whitelisted_service(self):
        assert normalize_dumpsys_service("activity") == "activity"
        assert normalize_dumpsys_service("netstats") == "netstats"

    @pytest.mark.parametrize("bad", ["gfxinfo", "wakelocks", "activity;reboot", "foo bar"])
    def test_non_whitelisted_rejected(self, bad):
        with pytest.raises(ValueError):
            normalize_dumpsys_service(bad)

    def test_whitelist_integrity(self):
        for svc in DUMPSYS_SERVICES:
            assert svc == svc.strip()
            assert not any(ch in svc for ch in " ;$&|()<>")
        assert "activity" in DUMPSYS_SERVICES
        assert "meminfo" in DUMPSYS_SERVICES


class TestNormalizeGeoCoordinate:
    def test_valid_coordinate(self):
        assert (
            normalize_geo_coordinate(
                "12.5", minimum=Decimal("-90"), maximum=Decimal("90")
            )
            == "12.5"
        )

    @pytest.mark.parametrize("bad", ["abc", "1;2", "1 2", "1,2", ""])
    def test_invalid_rejected(self, bad):
        with pytest.raises(ValueError):
            normalize_geo_coordinate(bad, minimum=Decimal("-90"), maximum=Decimal("90"))

    def test_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            normalize_geo_coordinate("91", minimum=Decimal("-90"), maximum=Decimal("90"))


class TestTruncateDiagnosticOutput:
    def test_truncation(self):
        text, truncated = truncate_diagnostic_output("a\nb\nc\nd\ne", max_lines=3)
        assert text == "a\nb\nc"
        assert truncated is True

    def test_no_truncation(self):
        text, truncated = truncate_diagnostic_output("a\nb", max_lines=10)
        assert text == "a\nb"
        assert truncated is False
