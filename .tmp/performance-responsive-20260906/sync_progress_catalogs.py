"""只追加本轮进度文案，验证此前词条及原文件字节未被改写。"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS = {
    "采集进度": ("採集進度", "Collection progress"),
    "进度按计划时长估算，报告生成后才确认完成。": (
        "進度按計劃時長估算，報告產生後才確認完成。",
        "Progress is estimated from the planned duration. Completion is confirmed after the report is generated.",
    ),
    "正在停止采集并生成报告，请稍候。": (
        "正在停止採集並產生報告，請稍候。",
        "Stopping collection and generating the report. Please wait.",
    ),
    "已达到计划时长，等待采集结束与报告生成。": (
        "已達到計劃時長，等待採集結束與報告產生。",
        "Planned duration reached. Waiting for collection to end and the report to be generated.",
    ),
    "预计进度 {percent}% · 已用 {elapsed} / 计划 {duration}": (
        "預計進度 {percent}% · 已用 {elapsed} / 計劃 {duration}",
        "Estimated progress {percent}% · Elapsed {elapsed} / Planned {duration}",
    ),
    "报告已生成，可查看图表或打开结果目录。": (
        "報告已產生，可查看圖表或開啟結果目錄。",
        "The report is ready. View charts or open the results folder.",
    ),
    "采集已停止，已生成的结果会保留。": (
        "採集已停止，已產生的結果會保留。",
        "Collection stopped. Generated results are preserved.",
    ),
    "采集失败，请查看运行日志后重试。": (
        "採集失敗，請查看執行日誌後重試。",
        "Collection failed. Check the run log and try again.",
    ),
    "配置采集参数后开始，运行期间可查看日志。": (
        "設定採集參數後開始，執行期間可查看日誌。",
        "Configure collection parameters, then start. Logs are available while running.",
    ),
    "已停止": ("已停止", "Stopped"),
    "暂无方案，请先保存": ("暫無方案，請先儲存", "No presets yet. Save one first"),
}


def messages(raw: bytes) -> dict[str, str]:
    result = {}
    for message in ET.fromstring(raw).findall("./context/message"):
        source = message.findtext("source")
        assert source and source not in result
        result[source] = message.findtext("translation") or ""
    return result


def main() -> None:
    report = []
    for language in ("zh_CN", "zh_HK", "en_US"):
        path = ROOT / "resources" / "i18n" / f"adblab.{language}.ts"
        before = path.read_bytes()
        existing = messages(before)
        newline = "\r\n" if b"\r\n" in before else "\n"
        blocks = []
        additions = {}
        for source, (traditional, english) in TRANSLATIONS.items():
            translated = {"zh_CN": source, "zh_HK": traditional, "en_US": english}[language]
            if source in existing:
                assert existing[source] == translated, (language, source, existing[source])
                continue
            additions[source] = translated
            blocks.append(newline.join((
                "        <message>",
                f"            <source>{escape(source)}</source>",
                f"            <translation>{escape(translated)}</translation>",
                "        </message>",
                "",
            )))
        marker = b"    </context>"
        assert before.count(marker) == 1
        block = "".join(blocks).encode("utf-8")
        after = before.replace(marker, block + marker, 1)
        assert after.replace(block + marker, marker, 1) == before
        resulting = messages(after)
        assert all(resulting[source] == value for source, value in existing.items())
        assert len(resulting) == len(existing) + len(additions)
        if additions:
            path.write_bytes(after)
        report.append({
            "language": language,
            "existing_entries_preserved": len(existing),
            "new_entries": additions,
            "before_sha256": hashlib.sha256(before).hexdigest(),
            "after_sha256": hashlib.sha256(after).hexdigest(),
            "existing_bytes_preserved": True,
        })
    report_path = Path(__file__).with_name("progress-catalog-sync.json")
    if any(item["new_entries"] for item in report):
        history = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else []
        report_path.write_text(json.dumps(history + report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
