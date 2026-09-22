"""控制台编码修正。

Windows 上 Python 的 stdout 默认跟随控制台代码页（cp936 / cp1252 / …），
直接 `print("中文")` 在 cp1252 等代码页下会抛 `UnicodeEncodeError` 把程序搞崩 ——
GitHub Actions 的 windows runner 就是这个情况。

在**程序入口**（run.py / build_exe.py）调用一次 `setup_console()` 即可，
不要做成 import 副作用，库模块不该偷偷改全局状态。
"""
from __future__ import annotations

import sys


def setup_console() -> None:
    """把标准输出/错误切到 UTF-8，并尽量让 Windows 控制台也切到 UTF-8 代码页。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
