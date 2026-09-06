"""只补入本轮页面布局新增词条，保留既有翻译和词条顺序。"""
from pathlib import Path
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS = {
    "Monkey 运行状态": ("Monkey status", "Monkey 執行狀態"),
    "事件分布": ("Event distribution", "事件分佈"),
    "勾选后遇到相应异常仍继续测试。": ("Continue testing when the selected exceptions occur.", "勾選後遇到相應異常仍繼續測試。"),
    "图表在采集结束后生成；运行期间可查看日志。": ("Charts are generated after collection ends. View logs while collection is running.", "圖表在採集結束後產生；執行期間可查看日誌。"),
    "已填入当前应用，可继续编辑包名。": ("Current app filled in. You can edit the package name.", "已填入目前應用程式，可繼續編輯套件名稱。"),
    "开始时自动核对包信息，通过后执行当前参数。": ("Starting verifies package information, then runs with the current parameters.", "開始時自動核對套件資訊，通過後執行目前參數。"),
    "异常处理": ("Exception handling", "異常處理"),
    "未填写包名，将读取各设备前台应用。": ("No package specified. The foreground app on each device will be read.", "未填寫套件名稱，將讀取各裝置的前景應用程式。"),
    "未能读取当前应用，请手动输入包名或重试。": ("Could not read the current app. Enter a package name or retry.", "未能讀取目前應用程式，請手動輸入套件名稱或重試。"),
    "正在核对测试包信息，可取消本次获取。": ("Verifying test package information. You can cancel this lookup.", "正在核對測試套件資訊，可取消本次取得。"),
    "正在读取当前应用…": ("Reading the current app…", "正在讀取目前應用程式…"),
    "正在运行 · {count} 台设备": ("Running · {count} devices", "正在執行 · {count} 部裝置"),
    "测试目标": ("Test target", "測試目標"),
    "设置堆快照、异常关键字与设备日志；收起时保留配置。": ("Configure heap dumps, exception keywords, and device logs. Collapsing preserves these settings.", "設定堆積快照、異常關鍵字與裝置日誌；收起時保留設定。"),
    "诊断选项": ("Diagnostic options", "診斷選項"),
    "读取中…": ("Reading…", "讀取中…"),
    "运行参数": ("Run parameters", "執行參數"),
    "采集计划": ("Collection plan", "採集計劃"),
}

for language in ("zh_CN", "en_US", "zh_HK"):
    path = ROOT / "resources" / "i18n" / f"adblab.{language}.ts"
    original = path.read_text(encoding="utf-8")
    context = next(c for c in ET.fromstring(original).findall("context") if c.findtext("name") == "ADBLab")
    known = {m.findtext("source") for m in context.findall("message")}
    messages = []
    for source, (english, traditional) in sorted(TRANSLATIONS.items()):
        if source in known:
            continue
        translation = {"zh_CN": source, "en_US": english, "zh_HK": traditional}[language]
        messages.append(f"        <message>\n            <source>{escape(source)}</source>\n            <translation>{escape(translation)}</translation>\n        </message>\n")
    updated = original.replace("    </context>", "".join(messages) + "    </context>", 1)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
    print(language, len(messages))
