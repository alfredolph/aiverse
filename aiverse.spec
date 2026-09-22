# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 生成单文件 AIVerse.exe。

用法：
    python -m PyInstaller --clean --noconfirm aiverse.spec
或直接：
    python build_exe.py
"""
import os

from PyInstaller.utils.hooks import collect_submodules

# 后端是动态导入的包，显式收集全部子模块，避免漏打
hidden = collect_submodules("backend")

# FFmpeg 随程序自带：它是导出成片的唯一硬依赖，不该等 39 GB 的 H3 权重下载完。
# 抓不到（离线构建、或手动 --no-ffmpeg）时照样能打包，只是导出前得先装 FFmpeg。
# 运行时查找顺序见 backend/media/ffmpeg.py 的 _bin_dirs()。
_datas = [("frontend", "frontend")]
_ffmpeg_dir = "assets/ffmpeg"
if os.path.isdir(_ffmpeg_dir) and os.path.isfile(os.path.join(_ffmpeg_dir, "bin", "ffmpeg.exe")):
    print(f"[spec] 内置 FFmpeg：{_ffmpeg_dir}")
    # 只带 ffmpeg.exe / ffprobe.exe —— ffplay 是播放器，程序用不到，白占 80 MB
    _bin = os.path.join(_ffmpeg_dir, "bin")
    for _n in sorted(os.listdir(_bin)):
        if _n.startswith("ffmpeg.") or _n.startswith("ffprobe."):
            _datas.append((os.path.join(_bin, _n), "ffmpeg/bin"))
else:
    print("[spec] 未找到 assets/ffmpeg/bin/ffmpeg.exe —— 打包出的 exe 不自带 FFmpeg")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    # 前端静态资源必须打进包里
    datas=_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 本项目零第三方依赖，把用不到的重型库排除以压缩体积。
    # 注意：http.server / urllib 依赖 html、email、http.cookiejar 等标准库，
    # 这些绝不能排除，否则服务启动即崩。
    excludes=[
        "tkinter", "numpy", "pandas", "scipy", "matplotlib", "PIL",
        "pytest", "setuptools", "pip", "wheel", "lib2to3", "distutils",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AIVerse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 保留控制台：用户可以看到端口、GPU、日志，关闭窗口即退出服务
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/aiverse.ico",
    version="assets/version_info.txt",
)
