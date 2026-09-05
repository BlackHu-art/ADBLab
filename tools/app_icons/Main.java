package com.adblab.icons;

import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.os.Looper;
import android.util.Base64;

import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.reflect.Method;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

/** 临时 app_process 入口：读取当前用户的原生 Drawable，并输出有界 PNG 行协议。 */
public final class Main {
    private static final int SIZE = 96;
    private static final int MAX_BYTES = 256 * 1024;
    private static final int MAX_PACKAGES = 12;
    private static final long MAX_RUNTIME_MS = 15_000;
    private static final Pattern PACKAGE = Pattern.compile(
            "(?:android|[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+)");

    private Main() {}

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

    private static byte[] render(Drawable drawable) throws Exception {
        Bitmap bitmap = Bitmap.createBitmap(SIZE, SIZE, Bitmap.Config.ARGB_8888);
        try {
            Canvas canvas = new Canvas(bitmap);
            drawable.setBounds(0, 0, SIZE, SIZE);
            drawable.draw(canvas);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, bytes)) {
                throw new IllegalStateException("RENDER_FAILED");
            }
            return bytes.toByteArray();
        } finally {
            bitmap.recycle();
        }
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
        if (args.length == 0 || args.length > MAX_PACKAGES) {
            return;
        }
        Set<String> seen = new HashSet<>();
        for (String pkg : args) {
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
            for (String pkg : args) {
                protocol.println("ERROR\t" + pkg + "\tCONTEXT_UNAVAILABLE");
            }
            return;
        }
        for (String pkg : args) {
            try {
                if (currentUser() != user) {
                    protocol.println("ERROR\t" + pkg + "\tUSER_CHANGED");
                    continue;
                }
                byte[] png = render(manager.getApplicationIcon(pkg));
                if (currentUser() != user) {
                    protocol.println("ERROR\t" + pkg + "\tUSER_CHANGED");
                } else if (png.length > MAX_BYTES) {
                    protocol.println("ERROR\t" + pkg + "\tTOO_LARGE");
                } else {
                    protocol.println("ICON\t" + pkg + "\t" + Base64.encodeToString(png, Base64.NO_WRAP));
                }
            } catch (PackageManager.NameNotFoundException failure) {
                protocol.println("ERROR\t" + pkg + "\tNOT_FOUND");
            } catch (Throwable failure) {
                protocol.println("ERROR\t" + pkg + "\tRENDER_FAILED");
            }
        }
    }
}
