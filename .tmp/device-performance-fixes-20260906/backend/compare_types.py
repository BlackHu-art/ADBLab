"""比较本轮三个内核文件与隔离基线的 Pyright 诊断，不替换工作树。"""

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys


root = Path(__file__).resolve().parents[3]
audit = Path(__file__).resolve().parent
paths = (
    "mobileperf/android/monkey.py",
    "mobileperf/android/startup.py",
    "mobileperf/android/tools/androiddevice.py",
)
baseline_paths = []
for path in paths:
    target = audit / "type-baseline" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    source = audit / (path.replace("/", "__") + ".baseline")
    target.write_bytes(source.read_bytes())
    baseline_paths.append(str(target))

counts = {}
for label, targets in (("baseline", baseline_paths), ("current", paths)):
    completed = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", *targets],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    (audit / f"pyright-{label}.json").write_text(completed.stdout, encoding="utf-8")
    payload = json.loads(completed.stdout)
    counts[label] = Counter(
        (Path(item["file"]).name, item.get("rule"), item["message"])
        for item in payload["generalDiagnostics"]
    )
    print(label, "exit", completed.returncode, payload["summary"])

added = counts["current"] - counts["baseline"]
removed = counts["baseline"] - counts["current"]
for label, changes in (("ADDED", added), ("REMOVED", removed)):
    for diagnostic, count in changes.items():
        print(label, count, diagnostic)
