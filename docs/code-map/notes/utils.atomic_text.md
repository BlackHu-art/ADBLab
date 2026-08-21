---
kind: file
---

# utils.atomic_text

> 原子文本写入：临时文件 + os.replace，避免中途失败留下半截文件

- 路径：utils/atomic_text.py

## 函数

- [[utils.atomic_text.atomic_write_text]] — 把文本先写入同目录临时文件，再原子替换到目标路径

