package com.adblab.icons;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.res.Resources;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.os.Looper;
import android.os.Build;
import android.util.Base64;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.reflect.Method;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Date;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/** 临时 app_process 入口：读取当前用户的图标或轻量元数据，输出有界行协议。 */
public final class Main {
    private static final int SIZE = 96;
    private static final int MAX_BYTES = 256 * 1024;
    private static final int MAX_PACKAGES = 12;
    private static final int MAX_METADATA_PACKAGES = 30;
    private static final int MAX_METADATA_BYTES = 16 * 1024;
    private static final long MAX_RUNTIME_MS = 15_000;
    private static final Pattern PACKAGE = Pattern.compile(
            "(?:android|[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+)");

    private Main() {}

    /** 绘制与编码共用资源清理边界，但必须保留原始失败阶段。 */
    private static final class RenderFailure extends Exception {
        final String stage;

        RenderFailure(String stage, Throwable cause) {
            super(null, cause, false, false);
            this.stage = stage;
        }
    }

    /** 只传固定诊断枚举，不把异常正文、类名或堆栈写入设备响应。 */
    private static String renderFailureCode(String stage, Throwable failure) {
        if (failure instanceof RenderFailure) {
            stage = ((RenderFailure) failure).stage;
            failure = failure.getCause();
        }
        String kind;
        if (failure instanceof SecurityException) {
            kind = "SECURITY";
        } else if (failure instanceof IllegalArgumentException) {
            kind = "ARGUMENT";
        } else if (failure instanceof IllegalStateException) {
            kind = "STATE";
        } else if (failure instanceof Resources.NotFoundException) {
            kind = "RESOURCE";
        } else if (failure instanceof OutOfMemoryError) {
            kind = "MEMORY";
        } else {
            kind = "OTHER";
        }
        return "RENDER_FAILED:" + stage + ":" + kind;
    }

    private static int currentUser() throws Exception {
        Class<?> activityManager = Class.forName("android.app.ActivityManager");
        return (Integer) activityManager.getMethod("getCurrentUser").invoke(null);
    }

    // app_process 没有 Application 启动过程，必须主动准备框架依赖的主 Looper。
    @SuppressWarnings("deprecation")
    private static PackageManager packageManager(int userId) throws Exception {
        if (Looper.myLooper() == null) {
            Looper.prepareMainLooper();
        }
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        Class<?> userHandle = Class.forName("android.os.UserHandle");
        // 旧 Android 已有这两个入口；不依赖较晚加入的 of/createContextAsUser。
        Object user = userHandle.getConstructor(int.class).newInstance(userId);
        Method createContext = Context.class.getMethod(
                "createPackageContextAsUser", String.class, int.class, userHandle);
        Context userContext = (Context) createContext.invoke(context, "android", 0, user);
        return userContext.getPackageManager();
    }

    /** 部分 ROM 的系统图标入口访问受限接口时，改读应用声明的资源；仍经过包管理权限边界。 */
    private static Drawable loadIcon(PackageManager manager, String pkg) throws Exception {
        try {
            return manager.getApplicationIcon(pkg);
        } catch (SecurityException denied) {
            ApplicationInfo info = manager.getApplicationInfo(pkg, 0);
            // 未声明图标的应用沿用 PackageManager 语义，读取设备提供的默认 Drawable。
            if (info.icon == 0) {
                return manager.getDefaultActivityIcon();
            }
            return manager.getResourcesForApplication(info).getDrawable(info.icon, null);
        }
    }

    private static byte[] render(Drawable drawable) throws Exception {
        Bitmap bitmap = Bitmap.createBitmap(SIZE, SIZE, Bitmap.Config.ARGB_8888);
        String stage = "DRAW";
        try {
            Canvas canvas = new Canvas(bitmap);
            drawable.setBounds(0, 0, SIZE, SIZE);
            drawable.draw(canvas);
            stage = "ENCODE";
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, bytes)) {
                throw new IllegalStateException("RENDER_FAILED");
            }
            return bytes.toByteArray();
        } catch (Throwable failure) {
            throw new RenderFailure(stage, failure);
        } finally {
            bitmap.recycle();
        }
    }

    @SuppressWarnings("deprecation")
    private static JSONObject metadata(PackageManager manager, String pkg, int user) throws Exception {
        // 直接按包查询，保留禁用应用和没有 launcher 入口的系统组件。
        PackageInfo info = manager.getPackageInfo(pkg, 0);
        long code = Build.VERSION.SDK_INT >= 28
                ? info.getLongVersionCode() : ((long) info.versionCode & 0xffffffffL);
        JSONObject data = new JSONObject();
        data.put("user", user);
        data.put("label", manager.getApplicationLabel(info.applicationInfo).toString());
        data.put("version_name", info.versionName == null ? "" : info.versionName);
        data.put("version_code", Long.toString(code));
        // 设备本地日期与 dumpsys 的既有展示一致，不受主机时区影响。
        data.put("installed", new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT)
                .format(new Date(info.firstInstallTime)));
        data.put("updated", info.lastUpdateTime);
        data.put("source", info.applicationInfo.sourceDir + "\n"
                + Arrays.toString(info.applicationInfo.splitSourceDirs));
        // 包含语言、密度、夜间模式等资源限定条件，避免跨配置复用旧图标。
        data.put("configuration", manager.getResourcesForApplication(info.applicationInfo)
                .getConfiguration().toString());
        return data;
    }

    private static boolean sameIdentity(JSONObject before, JSONObject after) throws Exception {
        // 与主机指纹使用同组字段；名称和安装日期不决定图标是否可复用。
        for (String key : new String[] {"user", "version_name", "version_code", "updated",
                "source", "configuration"}) {
            if (!before.get(key).equals(after.get(key))) {
                return false;
            }
        }
        return true;
    }

    public static void main(String[] args) throws Exception {
        try {
            startWatchdog();
            run(args);
        } finally {
            // systemMain 可启动框架线程；处理完本批后显式退出，不留下后台 app_process。
            System.exit(0);
        }
    }

    private static void startWatchdog() {
        // 主机 ADB 超时不代表远端进程已退出；独立线程约束框架查询和原生绘制的总寿命。
        Thread watchdog = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    Thread.sleep(MAX_RUNTIME_MS);
                } catch (InterruptedException failure) {
                    // 意外中断只能提前终止本批，不能延长设备端进程的退出期限。
                    Thread.currentThread().interrupt();
                }
                System.exit(124);
            }
        }, "adblab-icon-deadline");
        watchdog.setDaemon(true);
        watchdog.start();
    }

    private static void run(String[] args) throws Exception {
        PrintStream protocol = new PrintStream(System.out, true, "UTF-8");
        // 框架初始化的诊断不能混入行协议；原始异常也不输出到主机。
        System.setOut(new PrintStream(new OutputStream() {
            @Override public void write(int value) {}
        }));
        boolean metadata = args.length > 0 && "--metadata".equals(args[0]);
        boolean iconMetadata = args.length > 0 && "--icons-metadata".equals(args[0]);
        int first = metadata || iconMetadata ? 1 : 0;
        int limit = metadata ? MAX_METADATA_PACKAGES : MAX_PACKAGES;
        String errorKind = metadata ? "META_ERROR" : "ERROR";
        if (args.length <= first || args.length - first > limit) {
            return;
        }
        Set<String> seen = new HashSet<>();
        for (int index = first; index < args.length; index++) {
            String pkg = args[index];
            if (pkg.length() > 255 || !PACKAGE.matcher(pkg).matches() || !seen.add(pkg)) {
                return;
            }
        }
        PackageManager manager;
        int user;
        try {
            user = currentUser();
            manager = packageManager(user);
        } catch (Throwable failure) {
            for (int index = first; index < args.length; index++) {
                protocol.println(errorKind + "\t" + args[index] + "\tCONTEXT_UNAVAILABLE");
            }
            return;
        }
        for (int index = first; index < args.length; index++) {
            String pkg = args[index];
            String stage = "METADATA";
            try {
                if (currentUser() != user) {
                    protocol.println(errorKind + "\t" + pkg + "\tUSER_CHANGED");
                    continue;
                }
                JSONObject before = metadata || iconMetadata ? metadata(manager, pkg, user) : null;
                byte[] record = before == null ? new byte[0] : before.toString().getBytes("UTF-8");
                byte[] png = new byte[0];
                if (!metadata) {
                    stage = "LOAD";
                    Drawable drawable = loadIcon(manager, pkg);
                    stage = "DRAW";
                    png = render(drawable);
                }
                // 将身份与本次像素绑定；两次独立 helper 调用之间可能发生用户切换或应用更新。
                stage = "METADATA";
                JSONObject after = iconMetadata ? metadata(manager, pkg, user) : null;
                if (currentUser() != user) {
                    protocol.println(errorKind + "\t" + pkg + "\tUSER_CHANGED");
                } else if (iconMetadata && !sameIdentity(before, after)) {
                    protocol.println(errorKind + "\t" + pkg + "\tIDENTITY_CHANGED");
                } else if (record.length > MAX_METADATA_BYTES || png.length > MAX_BYTES) {
                    protocol.println(errorKind + "\t" + pkg + "\tTOO_LARGE");
                } else if (metadata) {
                    protocol.println("META\t" + pkg + "\t"
                            + Base64.encodeToString(record, Base64.NO_WRAP));
                } else if (iconMetadata) {
                    protocol.println("ICON_META\t" + pkg + "\t"
                            + Base64.encodeToString(record, Base64.NO_WRAP) + "\t"
                            + Base64.encodeToString(png, Base64.NO_WRAP));
                } else {
                    protocol.println("ICON\t" + pkg + "\t"
                            + Base64.encodeToString(png, Base64.NO_WRAP));
                }
            } catch (PackageManager.NameNotFoundException failure) {
                protocol.println(errorKind + "\t" + pkg + "\tNOT_FOUND");
            } catch (Throwable failure) {
                protocol.println(errorKind + "\t" + pkg + "\t"
                        + (metadata ? "READ_FAILED" : renderFailureCode(stage, failure)));
            }
        }
    }
}
