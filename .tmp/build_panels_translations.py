import ctypes
import json
from pathlib import Path
from string import Formatter

sources = json.loads(Path('.tmp/panels-sources.json').read_text(encoding='utf-8'))
english = {}
for line in Path('.tmp/panels-english.tsv').read_text(encoding='utf-8').splitlines():
    index, value = line.split('\t', 1)
    english[int(index)] = value.replace('\\n', '\n')
assert set(english) == set(range(len(sources)))
lcmap = ctypes.windll.kernel32.LCMapStringEx
lcmap.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_longlong]
lcmap.restype = ctypes.c_int
def traditional(source):
    buffer = ctypes.create_unicode_buffer(len(source) * 3 + 10)
    assert lcmap('zh-HK', 0x04000000, source, len(source), buffer, len(buffer), None, None, 0)
    text = buffer.value
    for old, new in (
        ('設備', '裝置'), ('設置', '設定'), ('應用包', '應用程式套件'),
        ('應用程序', '應用程式'), ('應用管理', '應用程式管理'),
        ('當前應用', '目前應用程式'), ('前台應用', '前景應用程式'),
        ('應用切換', '應用程式切換'), ('應用的', '應用程式的'),
        ('屏幕', '螢幕'), ('內存', '記憶體'), ('文件', '檔案'),
        ('刷新', '重新整理'), ('日志', '日誌'), ('軟件', '軟件'),
        ('性能', '效能'), ('默認', '預設'), ('信息', '資訊'),
        ('當前', '目前'), ('正在運行', '執行中'), ('運行', '執行'),
        ('錄屏', '螢幕錄影'), ('采集', '採集'), ('快捷', '快速'),
        ('連接', '連線'), ('保存', '儲存'), ('端口', '連接埠'),
        ('隊列', '佇列'), ('加載', '載入'), ('數據', '資料'),
        ('卸載', '解除安裝'), ('網絡', '網絡'), ('列表', '清單'),
        ('會話', '工作階段'), ('重啟', '重新啟動'), ('觸摸', '觸控'),
        ('后', '後'),
    ):
        text = text.replace(old, new)
    return text
rows = [dict(source=source, en_US=english[index], zh_HK=traditional(source))
        for index, source in enumerate(sources) if source != '设']
extras = [
    ('充电中', 'Charging'), ('使用电池', 'On battery'),
    ('未充电', 'Not charging'), ('已充满', 'Fully charged'),
    ('第 {index} 台设备无法获取前台应用，请输入测试包名后重试', 'Could not read the foreground app on device {index}. Enter a test package name and retry'),
    ('第 {index} 台设备无法查询已安装应用，请检查连接与调试授权', 'Could not query installed apps on device {index}. Check its connection and debugging authorization'),
    ('第 {index} 台设备未安装目标应用，请先安装后重试', 'The target app is not installed on device {index}. Install it and retry'),
    ('第 {index} 台设备无法获取测试包信息，请重试', 'Could not query test package information on device {index}. Try again'),
    ('第 {index} 台设备返回的包信息不匹配，请重新获取', 'Package information from device {index} does not match. Query it again'),
    ('所选设备的前台应用不一致，请输入要测试的包名', 'Selected devices have different foreground apps. Enter the package name to test'),
    ('请先选择测试设备', 'Select test devices first'),
    ('应用包名格式无效，请输入完整包名后重试', 'Invalid package name. Enter the full package name and retry'),
    ('获取测试包信息失败，请检查连接后重试', 'Could not query test package information. Check the connection and retry'),
]
for source, english in extras:
    rows.append(dict(source=source, en_US=english, zh_HK=traditional(source)))
for line in Path('.tmp/panel-task-translations.tsv').read_text(encoding='utf-8').splitlines():
    source, english = line.split('\t', 1)
    rows.append(dict(source=source, en_US=english, zh_HK=traditional(source)))
for source, chinese in (
    ('Smooth', '流畅'), ('Balanced', '均衡'), ('Quality', '画质优先'),
    ('Low Latency', '低延迟'), ('Default', '默认'), ('System', '系统'),
    ('Bootloader', '引导加载程序'), ('Recovery', '恢复模式'), ('Fastboot', '快速启动模式'),
    ('Please enter IP and port, e.g. 192.168.1.10:5555', '请输入 IP 地址和端口，例如 192.168.1.10:5555'),
    ('Please enter a valid IP address, e.g. 192.168.1.10:5555', '请输入有效 IP 地址，例如 192.168.1.10:5555'),
    ('Port must be a number between 1 and 65535', '端口必须是 1 到 65535 之间的数字'),
    ('Port must be between 1 and 65535', '端口必须在 1 到 65535 之间'),
    ('Please enter IP and port, e.g. [::1]:5555', '请输入 IP 地址和端口，例如 [::1]:5555'),
    ('Please enter complete IP and port, e.g. 192.168.1.10:5555', '请输入完整 IP 地址和端口，例如 192.168.1.10:5555'),
):
    rows.append(dict(source=source, en_US=source, zh_CN=chinese, zh_HK=traditional(chinese)))
for row in rows:
    source_fields = {name for _, name, _, _ in Formatter().parse(row['source']) if name}
    for language in ('en_US', 'zh_HK'):
        assert {name for _, name, _, _ in Formatter().parse(row[language]) if name} == source_fields, row
output = Path('C:/Users/Administrator/.codex/visualizations/2026/09/06/01a07503-4fb6-7773-b182-2628672892d3/panels-translations.json')
output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
print('rows:', len(rows))
