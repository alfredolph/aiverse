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

# Windows CI runner 的控制台默认是 cp1252，直接 print 中文会 UnicodeEncodeError。
# 这里强制把标准输出切成 UTF-8，避免构建脚本本身把自己搞挂。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    skip_ffmpeg = "--no-ffmpeg" in sys.argv

    print("\n[1/5] 生成应用图标")
    run([sys.executable, str(ROOT / "tools" / "make_icon.py")])

    print("\n[2/5] 取 FFmpeg（随程序自带，导出成片开箱可用）")
    if skip_ffmpeg:
        print("  – 已用 --no-ffmpeg 跳过；这样打出来的包导出时会提示先装 FFmpeg")
    else:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "fetch_ffmpeg.py")],
                           cwd=ROOT)
        if r.returncode != 0:
            print("  ! FFmpeg 没抓到（不影响打包，但用户导出前得先装 FFmpeg）")

    print("\n[3/5] 清理旧构建")
    for d in (ROOT / "build", DIST):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    print("\n[4/5] PyInstaller 打包（单文件模式，首次约需 1-3 分钟）")
    t0 = time.time()
    run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "aiverse.spec"])
    dt = time.time() - t0

    print("\n[5/5] 校验产物")
    if not EXE.exists():
        print("  ✗ 未生成 dist/AIVerse.exe，请检查上方日志")
        return 1
    size = EXE.stat().st_size
    print(f"  ✓ {EXE}")
    print(f"    体积 {human(size)} · 耗时 {dt:.0f}s")
    print("\n  双击 dist/AIVerse.exe 即可运行，浏览器会自动打开控制台。")
    print("  绿色版：数据与 30GB 推理运行时放在 exe 同级，可随 U 盘带走。")
    print("  安装版（iscc installer\\aiverse.iss）：统一放到 %LOCALAPPDATA%\\AIVerse，重装不丢模型。")
    print("\n  关于体积：")
    print("  · 内置 FFmpeg（约 80 MB，压缩后实际增量小得多）—— 导出成片开箱可用。")
    print("  · 真正的算力 MiniMax H3（33B 参数 / 精简版权重 39 GB 起）物理上无法打进 exe，")
    print("    由首次运行时的「⚡ 环境部署」自动安装，或走「离线包导入」零下载复制。")
    print("\n  想跑前端渲染冒烟测试：")
    print("    dist\\AIVerse.exe 8799 --no-open   然后   node tools/ui_smoke.js http://127.0.0.1:8799\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
