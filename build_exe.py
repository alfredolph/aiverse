"""一键打包 Windows 可执行文件。

用法：
    python build_exe.py

产物：
    dist/AIVerse.exe          单文件绿色版，双击即用
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
EXE = DIST / "AIVerse.exe"


def run(cmd: list[str], **kw) -> None:
    print("  $ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main() -> int:
    print("\n[1/4] 生成应用图标")
    run([sys.executable, str(ROOT / "tools" / "make_icon.py")])

    print("\n[2/4] 清理旧构建")
    for d in (ROOT / "build", DIST):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    print("\n[3/4] PyInstaller 打包（单文件模式，首次约需 1-3 分钟）")
    t0 = time.time()
    run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "aiverse.spec"])
    dt = time.time() - t0

    print("\n[4/4] 校验产物")
    if not EXE.exists():
        print("  ✗ 未生成 dist/AIVerse.exe，请检查上方日志")
        return 1
    size = EXE.stat().st_size
    print(f"  ✓ {EXE}")
    print(f"    体积 {human(size)} · 耗时 {dt:.0f}s")
    print("\n  双击 dist/AIVerse.exe 即可运行，浏览器会自动打开控制台。")
    print("  用户数据保存在 exe 同级的 projects/ 目录，可直接备份或迁移。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
