"""GPU 自动检测与推荐配置（文档 §19 / §20 / §21 / §22）。

启动时检测 GPU / VRAM / CUDA / 驱动 / RAM / CPU / 磁盘，并按显存给出推荐工作流配置。
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any

# 显存 -> 推荐配置（文档 §19）
VRAM_PROFILES = [
    (24, {"tier": "旗舰", "precision": "FP16", "resolution": "1080p+", "offload": False,
          "batch": 4, "note": "高质量模式，可开多任务并行"}),
    (16, {"tier": "高", "precision": "FP16 / W8", "resolution": "1080p", "offload": False,
          "batch": 2, "note": "更高配置，可跑 Ref2V 高质量档"}),
    (12, {"tier": "中", "precision": "W4", "resolution": "720p", "offload": True,
          "batch": 2, "note": "W4 + 部分 Offload"}),
    (8, {"tier": "入门", "precision": "NF4", "resolution": "768/480 级", "offload": True,
         "batch": 1, "note": "低显存工作流：NF4 + CPU Offload + 降分辨率"}),
    (0, {"tier": "仅 CPU / 云端", "precision": "—", "resolution": "480p", "offload": True,
         "batch": 1, "note": "建议使用云端 Provider 或 Hybrid 模式"}),
]


def _profile(vram_gb: float) -> dict:
    for threshold, prof in VRAM_PROFILES:
        if vram_gb >= threshold:
            return dict(prof)
    return dict(VRAM_PROFILES[-1][1])


def _nvidia_smi() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
        )
        gpus = []
        for line in (out.stdout or "").strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    mb = float(parts[1])
                except ValueError:
                    mb = 0.0
                gpus.append({"name": parts[0], "vram_mb": mb, "vram_gb": round(mb / 1024, 1),
                             "driver": parts[2] if len(parts) > 2 else ""})
        return gpus
    except Exception:
        return []


def _wmic_gpu() -> list[dict]:
    if platform.system() != "Windows":
        return []
    try:
        out = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name,AdapterRAM", "/format:csv"],
            capture_output=True, text=True, timeout=10,
        )
        gpus = []
        for line in (out.stdout or "").strip().splitlines()[1:]:
            cells = [c.strip() for c in line.split(",")]
            if len(cells) >= 3 and cells[2]:
                try:
                    mb = float(cells[2]) / (1024 * 1024)
                except ValueError:
                    mb = 0.0
                gpus.append({"name": cells[2], "vram_mb": round(mb), "vram_gb": round(mb / 1024, 1),
                             "driver": ""})
        return gpus
    except Exception:
        return []


def _sysinfo() -> dict:
    info = {"os": f"{platform.system()} {platform.release()}", "cpu": platform.processor() or "",
            "cpu_cores": os.cpu_count() or 0}
    try:
        if platform.system() == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            info["ram_gb"] = round(m.ullTotalPhys / (1024 ** 3), 1)
        else:
            pages = os.sysconf("SC_PHYS_PAGES")
            info["ram_gb"] = round(pages * os.sysconf("SC_PAGE_SIZE") / (1024 ** 3), 1)
    except Exception:
        info["ram_gb"] = 0
    try:
        from ..core.config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        info["disk_free_gb"] = round(shutil.disk_usage(str(DATA_DIR)).free / (1024 ** 3), 1)
    except Exception:
        info["disk_free_gb"] = 0
    return info


def detect() -> dict[str, Any]:
    gpus = _nvidia_smi() or _wmic_gpu()
    sysinfo = _sysinfo()
    cuda = bool(shutil.which("nvcc") or shutil.which("nvidia-smi"))
    top = max([g["vram_gb"] for g in gpus], default=0.0)
    prof = _profile(top)
    mode = "Local" if top >= 8 else ("Hybrid" if top > 0 else "Cloud")

    tips = []
    if top >= 8:
        tips.append(f"当前显卡可本地生产：建议 {prof['precision']} + "
                    f"{'开启' if prof['offload'] else '关闭'} CPU Offload，分辨率 {prof['resolution']}")
    else:
        tips.append("未检测到可用的本地 GPU，建议使用云端 Provider 或 Hybrid 模式")
    if sysinfo.get("ram_gb") and sysinfo["ram_gb"] < 32:
        tips.append(f"内存 {sysinfo['ram_gb']}GB，文档建议 32GB+ 以获得更稳的 Offload 表现")
    if len(gpus) > 1:
        tips.append(f"检测到 {len(gpus)} 块 GPU，可开启多卡任务调度（GPU0 视频 / GPU1 图像 / GPU2 放大）")

    return {
        "gpus": gpus or [{"name": "未检测到独立显卡", "vram_gb": 0.0, "vram_mb": 0, "driver": ""}],
        "cuda": cuda,
        "system": sysinfo,
        "recommend": prof,
        "mode": mode,
        "multi_gpu": len(gpus) > 1,
        "tips": tips,
    }
