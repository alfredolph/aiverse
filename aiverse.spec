# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 生成单文件 AIVerse.exe。

用法：
    python -m PyInstaller --clean --noconfirm aiverse.spec
或直接：
    python build_exe.py
"""
from PyInstaller.utils.hooks import collect_submodules

# 后端是动态导入的包，显式收集全部子模块，避免漏打
hidden = collect_submodules("backend")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    # 前端静态资源必须打进包里
    datas=[("frontend", "frontend")],
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
