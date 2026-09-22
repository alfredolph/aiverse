"""部署计划生成 —— 按硬件决定装什么。

核心逻辑：
  1. 读 GPU / 显存 / 内存 / 磁盘
  2. 按显存档位挑模型变体与加速节点（catalog.VRAM_TIERS）
  3. 生成一串可顺序执行的步骤，给出诚实的总体积与耗时预估
"""
from __future__ import annotations

from typing import Any

from ..core.config import RUNTIME_DIR
from ..gpu import detector as gpu
from . import catalog


def _size_human(gb: float) -> str:
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{gb * 1024:.0f} MB"


def build_plan(mirror: str = "cn", model_key: str | None = None,
               include_nodes: bool | None = None, include_ffmpeg: bool = True) -> dict[str, Any]:
    info = gpu.detect()
    top = info["gpus"][0]
    vram = float(top.get("vram_gb") or 0)
    tier = catalog.tier_for(vram)

    m = catalog.MIRRORS.get(mirror) or catalog.MIRRORS["cn"]
    model_key = model_key or tier["model"]
    if include_nodes is None:
        include_nodes = bool(tier["nodes"])

    rt = RUNTIME_DIR
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []

    def step(key: str, name: str, desc: str, kind: str, size_gb: float,
             cmd: list[str] | None = None, optional: bool = False,
             needs_gpu: bool = False, cwd: str | None = None) -> None:
        steps.append({
            "key": key, "name": name, "desc": desc, "kind": kind,
            "size_gb": round(size_gb, 3), "size_human": _size_human(size_gb),
            "cmd": cmd or [], "optional": optional, "needs_gpu": needs_gpu,
            "cwd": cwd or str(rt), "done": False,
        })

    # ---- 1. uv -----------------------------------------------------
    step("uv", "准备 uv 运行时管理器",
         "单文件 Python 包管理器，用来隔离安装，不污染系统 Python",
         "download_zip", 0.04,
         cmd=[str(rt / "uv" / "uv.exe"), "--version"])

    # ---- 2. Python -------------------------------------------------
    step("python", "安装 Python 3.12 隔离运行时",
         "独立运行时，卸载时整体删除即可，不影响系统环境",
         "exec", 0.03,
         cmd=[str(rt / "uv" / "uv.exe"), "python", "install", "3.12"])

    # ---- 3. 虚拟环境 -----------------------------------------------
    step("venv", "创建项目虚拟环境",
         "所有推理依赖装在这里，与系统完全隔离",
         "exec", 0.0,
         cmd=[str(rt / "uv" / "uv.exe"), "venv", str(rt / "venv"), "--python", "3.12"])

    # ---- 4. PyTorch ------------------------------------------------
    if vram >= 1:
        torch_cmd = [str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
                     "torch", "torchvision", "torchaudio",
                     "--index-url", m["torch_index"]]
        torch_size = 2.5
    else:
        torch_cmd = [str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
                     "torch", "torchvision", "torchaudio"]
        torch_size = 0.9
        warnings.append("未检测到 NVIDIA 显卡，将安装 CPU 版 PyTorch（可运行但极慢）")
    step("torch", "安装 PyTorch + CUDA 运行时",
         "GPU 推理基础库（cu124）。这是本地出片的算力底座",
         "exec", torch_size, cmd=torch_cmd, needs_gpu=True)

    # ---- 5. ComfyUI ------------------------------------------------
    step("comfyui", "部署 ComfyUI 执行引擎",
         "底层推理后端。界面上完全看不到节点，只作为 H3 的运行时",
         "exec", 1.2,
         cmd=[str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
              "comfy-cli"])
    step("comfyui-install", "初始化 ComfyUI 与基础依赖",
         "拉取 ComfyUI 本体并安装其依赖",
         "exec", 1.2,
         cmd=[str(rt / "venv" / "Scripts" / "comfy.exe"), "install", "--skip-manager",
              "--nvidia", "--workspace", str(rt / "comfyui"), "--yes"])

    # ---- 6. 加速节点（可选）----------------------------------------
    if include_nodes:
        step("comfy-nodes", "安装 H3 加速节点",
             "SageAttention + EasyCache，官方实测 15 秒视频 8 分钟 → 约 4 分钟",
             "exec", 0.35,
             cmd=[str(rt / "venv" / "Scripts" / "comfy.exe"), "node", "install",
                  "https://github.com/kijai/ComfyUI-KJNodes"],
             optional=True, needs_gpu=True)

    # ---- 7. H3 权重 ------------------------------------------------
    if model_key:
        md = catalog.MODEL_REPOS[model_key]
        repo = md["repo_modelscope"] if m["models"] == "modelscope" else md["repo_hf"]
        tool = "modelscope" if m["models"] == "modelscope" else "huggingface_hub"
        step("model-tool", f"安装模型下载工具（{tool}）",
             "用于从国内/海外镜像拉取 H3 权重，支持断点续传",
             "exec", 0.02,
             cmd=[str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
                  "modelscope", "huggingface_hub"])
        step("h3-weights", f"下载 {md['name']}",
             f"{md['desc']} 仓库：{repo}",
             "model_download", md["size_gb"],
             cmd=["--repo", repo, "--subdir", md["subdir"],
                  "--backend", m["models"], "--target", str(rt / "models" / "MiniMax-H3")],
             needs_gpu=True)
        if md["min_vram"] > vram > 0:
            warnings.append(
                f"当前显存 {vram:.0f}GB 低于该版本的推荐值 {md['min_vram']}GB，"
                f"会自动在显存/内存间交换，不会崩但速度慢"
            )
    else:
        warnings.append("跳过模型下载（无可用 GPU）。生成将走云端 Provider")

    # ---- 8. FFmpeg -------------------------------------------------
    if include_ffmpeg:
        step("ffmpeg", "部署 FFmpeg 7.1",
             "视频合成 / 转码 / 字幕烧录，导出 MP4 必需",
             "download_zip", 0.09)

    # ---- 9. 写入 H3 工作流与 Provider 配置 --------------------------
    step("wire", "接入 H3 工作流并注册 Provider",
         "写入 FL2VA / Ref2VA 工作流模板，把 H3 注册为视频 Provider",
         "wire", 0.0)

    total = sum(s["size_gb"] for s in steps)
    disk_free = float(info["system"].get("disk_free_gb") or 0)
    if disk_free and disk_free < total + 10:
        warnings.append(
            f"磁盘可用 {disk_free:.0f}GB，部署需要约 {total:.1f}GB + 运行余量 10GB，建议清理空间"
        )
    if float(info["system"].get("ram_gb") or 0) < 32 and vram and vram < 16:
        warnings.append(
            f"内存 {info['system']['ram_gb']}GB。低显存跑 H3 会大量使用内存做交换，"
            f"建议 32GB+，或在系统里把虚拟内存设到 64GB"
        )

    # 粗略耗时：按 12 MB/s 估算下载时间
    dl_minutes = total * 1024 / 12 / 60

    return {
        "ok": True,
        "runtime_dir": str(rt),
        "mirror": mirror,
        "mirror_name": m["name"],
        "gpu": {"name": top["name"], "vram_gb": vram, "driver": top.get("driver", "")},
        "system": info["system"],
        "tier": tier,
        "model": model_key,
        "model_name": catalog.MODEL_REPOS[model_key]["name"] if model_key else "（不下载）",
        "steps": steps,
        "total_download_gb": round(total, 2),
        "total_download_human": _size_human(total),
        "estimated_minutes": round(dl_minutes, 1),
        "warnings": warnings,
        "can_local": vram >= 8,
    }
