"""编译并运行真实设备 helper，以窄框架替身验证安全失败协议，不连接设备。"""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[1]
_PRIVATE_MESSAGE = "private-device-secret /private/installed/app.apk"

# JVM 不提供 Android 框架；替身只提供 Main 实际消费的 API 和明确故障点。
_FRAMEWORK = {
    "testsupport/Probe.java": """
        package testsupport;
        public final class Probe {
            public static String packageName = "";
            public static int metadataCalls;
            public static void hit(String stage) {
                if (!packageName.endsWith(".bad")) return;
                String requested = System.getProperty("probe.stage", "");
                boolean selected = requested.equals(stage)
                    || (requested.equals("METADATA_AFTER") && stage.equals("METADATA")
                        && metadataCalls > 1);
                if (!selected) return;
                String message = "private-device-secret /private/installed/app.apk";
                switch (System.getProperty("probe.kind", "OTHER")) {
                    case "SECURITY": throw new SecurityException(message);
                    case "ARGUMENT": throw new IllegalArgumentException(message);
                    case "STATE": throw new IllegalStateException(message);
                    case "RESOURCE":
                        throw new android.content.res.Resources.NotFoundException(message);
                    case "MEMORY": throw new OutOfMemoryError(message);
                    case "FALSE": return;
                    default: throw new UnsupportedOperationException(message);
                }
            }
        }
    """,
    "android/app/ActivityManager.java": """
        package android.app;
        public final class ActivityManager {
            public static int getCurrentUser() { return 0; }
        }
    """,
    "android/app/ActivityThread.java": """
        package android.app;
        public final class ActivityThread {
            public static ActivityThread systemMain() { return new ActivityThread(); }
            public android.content.Context getSystemContext() {
                return new android.content.Context();
            }
        }
    """,
    "android/content/Context.java": """
        package android.content;
        public class Context {
            public Context createPackageContextAsUser(String pkg, int flags,
                    android.os.UserHandle user) { return this; }
            public android.content.pm.PackageManager getPackageManager() {
                return new android.content.pm.PackageManager();
            }
        }
    """,
    "android/content/pm/ApplicationInfo.java": """
        package android.content.pm;
        public final class ApplicationInfo {
            public String sourceDir = "/synthetic/base.apk";
            public String[] splitSourceDirs = null;
            public int icon = 123;
        }
    """,
    "android/content/pm/PackageInfo.java": """
        package android.content.pm;
        public final class PackageInfo {
            public ApplicationInfo applicationInfo = new ApplicationInfo();
            public int versionCode = 1;
            public String versionName = "1";
            public long firstInstallTime = 1700000000000L;
            public long lastUpdateTime = 1700000000000L;
            public long getLongVersionCode() { return versionCode; }
        }
    """,
    "android/content/pm/PackageManager.java": """
        package android.content.pm;
        import testsupport.Probe;
        public class PackageManager {
            public static class NameNotFoundException extends Exception {}
            public PackageInfo getPackageInfo(String pkg, int flags) throws NameNotFoundException {
                if (!pkg.equals(Probe.packageName)) Probe.metadataCalls = 0;
                Probe.packageName = pkg;
                Probe.metadataCalls++;
                if (pkg.endsWith(".missing")) throw new NameNotFoundException();
                Probe.hit("METADATA");
                PackageInfo info = new PackageInfo();
                if (pkg.endsWith(".bad") && Probe.metadataCalls > 1
                        && (System.getProperty("probe.stage", "").equals("IDENTITY")
                            || System.getProperty("probe.fallback", "").equals("identity"))) {
                    info.lastUpdateTime++;
                }
                return info;
            }
            public CharSequence getApplicationLabel(ApplicationInfo info) { return "App"; }
            public ApplicationInfo getApplicationInfo(String pkg, int flags)
                    throws NameNotFoundException {
                if (System.getProperty("probe.fallback", "").equals("forbidden")) {
                    throw new AssertionError("Unnecessary resource fallback");
                }
                ApplicationInfo info = new ApplicationInfo();
                if (System.getProperty("probe.fallback", "").startsWith("zero")) info.icon = 0;
                return info;
            }
            public android.graphics.drawable.Drawable getDefaultActivityIcon() {
                String mode = System.getProperty("probe.fallback", "");
                if (mode.equals("zero_security")) throw new SecurityException("private-path");
                if (mode.equals("zero_resource")) {
                    throw new android.content.res.Resources.NotFoundException("private-path");
                }
                return new android.graphics.drawable.Drawable(2);
            }
            public android.content.res.Resources getResourcesForApplication(ApplicationInfo info) {
                return new android.content.res.Resources();
            }
            public android.graphics.drawable.Drawable getApplicationIcon(String pkg)
                    throws NameNotFoundException {
                Probe.packageName = pkg;
                if (pkg.endsWith(".missing")) throw new NameNotFoundException();
                Probe.hit("LOAD");
                return new android.graphics.drawable.Drawable();
            }
        }
    """,
    "android/content/res/Resources.java": """
        package android.content.res;
        public class Resources {
            public static class Theme {}
            public static class NotFoundException extends RuntimeException {
                public NotFoundException(String message) { super(message); }
            }
            public Configuration getConfiguration() { return new Configuration(); }
            public android.graphics.drawable.Drawable getDrawable(int resource, Theme theme) {
                String mode = System.getProperty("probe.fallback", "");
                if (mode.equals("resource_failure")) throw new NotFoundException("private-path");
                if (mode.equals("available") || mode.equals("zero") || mode.equals("identity")) {
                    return new android.graphics.drawable.Drawable(true);
                }
                throw new SecurityException("private-path");
            }
        }
    """,
    "android/content/res/Configuration.java": """
        package android.content.res;
        public final class Configuration {
            public String toString() { return "synthetic-configuration"; }
        }
    """,
    "android/graphics/Bitmap.java": """
        package android.graphics;
        import testsupport.Probe;
        public final class Bitmap {
            public enum Config { ARGB_8888 }
            public enum CompressFormat { PNG }
            public byte[] pixels = new byte[] {0};
            public static Bitmap createBitmap(int w, int h, Config config) { return new Bitmap(); }
            public boolean compress(CompressFormat format, int quality,
                    java.io.OutputStream out) throws java.io.IOException {
                Probe.hit("ENCODE");
                if (Probe.packageName.endsWith(".bad")
                        && System.getProperty("probe.kind", "").equals("FALSE")) return false;
                out.write(pixels);
                return true;
            }
            public void recycle() {
                try {
                    java.nio.file.Files.write(java.nio.file.Paths.get(System.getProperty("probe.recycled")),
                        new byte[] {1}, java.nio.file.StandardOpenOption.CREATE,
                        java.nio.file.StandardOpenOption.APPEND);
                } catch (java.io.IOException failure) { throw new AssertionError(failure); }
            }
        }
    """,
    "android/graphics/Canvas.java": """
        package android.graphics;
        public final class Canvas {
            public final Bitmap bitmap;
            public Canvas(Bitmap bitmap) { this.bitmap = bitmap; }
        }
    """,
    "android/graphics/drawable/Drawable.java": """
        package android.graphics.drawable;
        public class Drawable {
            private final int source;
            public Drawable() { this(0); }
            public Drawable(boolean declared) { this(declared ? 1 : 0); }
            public Drawable(int source) { this.source = source; }
            public void setBounds(int x, int y, int w, int h) {}
            public void draw(android.graphics.Canvas canvas) {
                testsupport.Probe.hit("DRAW");
                canvas.bitmap.pixels = source == 2 ? new byte[] {7, 8, 9}
                    : source == 1 ? new byte[] {4, 5, 6} : new byte[] {1, 2, 3};
            }
        }
    """,
    "android/os/Looper.java": """
        package android.os;
        public final class Looper {
            public static Looper myLooper() { return null; }
            public static void prepareMainLooper() {}
        }
    """,
    "android/os/UserHandle.java": """
        package android.os;
        public final class UserHandle { public UserHandle(int user) {} }
    """,
    "android/os/Build.java": """
        package android.os;
        public final class Build {
            public static final class VERSION { public static int SDK_INT = 33; }
        }
    """,
    "android/util/Base64.java": """
        package android.util;
        public final class Base64 {
            public static final int NO_WRAP = 2;
            public static String encodeToString(byte[] bytes, int flags) {
                return java.util.Base64.getEncoder().encodeToString(bytes);
            }
        }
    """,
    "org/json/JSONObject.java": """
        package org.json;
        public final class JSONObject {
            private final java.util.Map<String, Object> values = new java.util.HashMap<>();
            public void put(String key, Object value) { values.put(key, value); }
            public Object get(String key) { return values.get(key); }
            public String toString() { return "{}"; }
        }
    """,
}


@pytest.fixture(scope="module")
def helper_classes(tmp_path_factory):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("真实 Java helper 故障注入需要本机 JDK 的 javac/java")
    work = tmp_path_factory.mktemp("app-icon-java")
    sources = [_ROOT / "tools/app_icons/Main.java"]
    for filename, source in _FRAMEWORK.items():
        path = work / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        sources.append(path)
    classes = work / "classes"
    compiled = subprocess.run(
        [javac, "--release", "8", "-encoding", "UTF-8", "-d", str(classes),
         *(str(path) for path in sources)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    return java, classes


def run_helper(helper_classes, tmp_path, *, stage="", kind="OTHER", mode="--icons-metadata",
               packages=("com.example.bad", "com.example.good"), fallback=""):
    java, classes = helper_classes
    recycled = tmp_path / "recycled"
    result = subprocess.run(
        [java, f"-Dprobe.stage={stage}", f"-Dprobe.kind={kind}", f"-Dprobe.fallback={fallback}",
         f"-Dprobe.recycled={recycled}", "-cp", str(classes), "com.adblab.icons.Main",
         *([mode] if mode else []), *packages],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert _PRIVATE_MESSAGE not in result.stdout
    return result.stdout.splitlines(), recycled.read_bytes() if recycled.exists() else b""


@pytest.mark.parametrize("stage", ["METADATA", "LOAD", "DRAW", "ENCODE"])
@pytest.mark.parametrize("kind", ["SECURITY", "ARGUMENT", "STATE", "RESOURCE", "MEMORY", "OTHER"])
def test_failure_identifies_safe_stage_and_kind_then_continues(
    helper_classes, tmp_path, stage, kind,
):
    lines, recycled = run_helper(helper_classes, tmp_path, stage=stage, kind=kind)
    assert lines[0] == f"ERROR\tcom.example.bad\tRENDER_FAILED:{stage}:{kind}"
    assert lines[1] == "ICON_META\tcom.example.good\te30=\tAQID"
    assert len(lines) == 2
    assert len(recycled) == (2 if stage in {"DRAW", "ENCODE"} else 1)


def test_compress_false_reports_encode_failure_and_releases_bitmap(helper_classes, tmp_path):
    lines, recycled = run_helper(helper_classes, tmp_path, stage="ENCODE", kind="FALSE")
    assert lines == ["ERROR\tcom.example.bad\tRENDER_FAILED:ENCODE:STATE",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 2


def test_metadata_after_render_failure_is_not_misreported_as_draw(helper_classes, tmp_path):
    lines, recycled = run_helper(helper_classes, tmp_path, stage="METADATA_AFTER", kind="SECURITY")
    assert lines == ["ERROR\tcom.example.bad\tRENDER_FAILED:METADATA:SECURITY",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 2


def test_plain_icon_mode_also_delivers_safe_diagnostics(helper_classes, tmp_path):
    lines, _ = run_helper(helper_classes, tmp_path, stage="LOAD", kind="SECURITY", mode="")
    assert lines == ["ERROR\tcom.example.bad\tRENDER_FAILED:LOAD:SECURITY",
                     "ICON\tcom.example.good\tAQID"]


def test_metadata_mode_preserves_existing_failure_protocol(helper_classes, tmp_path):
    lines, recycled = run_helper(helper_classes, tmp_path, stage="METADATA", kind="SECURITY",
                                 mode="--metadata")
    assert lines == ["META_ERROR\tcom.example.bad\tREAD_FAILED",
                     "META\tcom.example.good\te30="]
    assert recycled == b""


def test_identity_change_still_prevents_icon_publication(helper_classes, tmp_path):
    lines, recycled = run_helper(helper_classes, tmp_path, stage="IDENTITY")
    assert lines == ["ERROR\tcom.example.bad\tIDENTITY_CHANGED",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 2


def test_missing_package_keeps_existing_error_and_does_not_stop_batch(helper_classes, tmp_path):
    lines, _ = run_helper(
        helper_classes, tmp_path, packages=("com.example.missing", "com.example.good"),
    )
    assert lines == ["ERROR\tcom.example.missing\tNOT_FOUND",
                     "ICON_META\tcom.example.good\te30=\tAQID"]


def test_security_denial_uses_declared_resource_and_releases_bitmaps(helper_classes, tmp_path):
    lines, recycled = run_helper(
        helper_classes, tmp_path, stage="LOAD", kind="SECURITY", fallback="available",
    )
    assert lines == ["ICON_META\tcom.example.bad\te30=\tBAUG",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 2


def test_normal_loading_does_not_enter_resource_fallback(helper_classes, tmp_path):
    lines, recycled = run_helper(helper_classes, tmp_path, fallback="forbidden")
    assert lines == ["ICON_META\tcom.example.bad\te30=\tAQID",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 2


@pytest.mark.parametrize("kind", ["ARGUMENT", "STATE", "RESOURCE", "MEMORY", "OTHER"])
def test_nonsecurity_failures_do_not_use_available_fallback(helper_classes, tmp_path, kind):
    lines, recycled = run_helper(
        helper_classes, tmp_path, stage="LOAD", kind=kind, fallback="available",
    )
    assert lines == [f"ERROR\tcom.example.bad\tRENDER_FAILED:LOAD:{kind}",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 1


def test_resource_fallback_failure_is_still_a_safe_load_failure(helper_classes, tmp_path):
    lines, recycled = run_helper(
        helper_classes, tmp_path, stage="LOAD", kind="SECURITY", fallback="resource_failure",
    )
    assert lines == ["ERROR\tcom.example.bad\tRENDER_FAILED:LOAD:RESOURCE",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 1


def test_undeclared_icon_uses_device_default_drawable_as_package_manager_does(
    helper_classes, tmp_path,
):
    lines, recycled = run_helper(
        helper_classes, tmp_path, stage="LOAD", kind="SECURITY", fallback="zero",
    )
    assert lines == ["ICON_META\tcom.example.bad\te30=\tBwgJ",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 2


@pytest.mark.parametrize("fallback,kind", [("zero_security", "SECURITY"),
                                          ("zero_resource", "RESOURCE")])
def test_default_drawable_failure_is_reported_without_substituting_pixels(
    helper_classes, tmp_path, fallback, kind,
):
    lines, recycled = run_helper(
        helper_classes, tmp_path, stage="LOAD", kind="SECURITY", fallback=fallback,
    )
    assert lines == [f"ERROR\tcom.example.bad\tRENDER_FAILED:LOAD:{kind}",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 1


def test_fallback_pixels_are_not_published_when_identity_changes(helper_classes, tmp_path):
    lines, recycled = run_helper(
        helper_classes, tmp_path, stage="LOAD", kind="SECURITY", fallback="identity",
    )
    assert lines == ["ERROR\tcom.example.bad\tIDENTITY_CHANGED",
                     "ICON_META\tcom.example.good\te30=\tAQID"]
    assert len(recycled) == 2
